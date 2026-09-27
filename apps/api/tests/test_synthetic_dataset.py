"""The synthetic generator is deterministic and the committed sample, examples and eval agree."""

import json
from collections import Counter
from pathlib import Path

from evals.run import (
    BASELINE,
    COMPARED_METRICS,
    SAMPLE,
    baseline_entry,
    compare_with_baseline,
    ensure_generated,
    load_dataset,
    score_cases,
)
from scripts.generate_synthetic import (
    DEFAULT_COUNT,
    DOCUMENT_TYPES,
    VARIANTS,
    example_cases,
    generate_dataset,
    sample_cases,
)

from app.llm.provider import MockInvoiceProvider
from app.llm.router import ModelRouter

ROOT = Path(__file__).parents[3]


def test_generation_is_deterministic_and_balanced() -> None:
    first, second = generate_dataset(), generate_dataset()
    assert [case.manifest_entry() for case in first] == [case.manifest_entry() for case in second]
    assert [case.pdf() for case in first[:12]] == [case.pdf() for case in second[:12]]
    assert len(first) == DEFAULT_COUNT == 150
    assert Counter(case.document_type for case in first) == {name: 50 for name in DOCUMENT_TYPES}
    assert set(Counter(case.variant for case in first)) == set(VARIANTS)
    assert len({case.name for case in first}) == 150
    assert all(case.should_flag for case in first if case.variant != "clean")
    assert all(not case.should_flag for case in first if case.variant == "clean")
    assert all(
        case.lines[0].lower().startswith(case.document_type.replace("_", " ")[:8]) for case in first
    )
    assert (
        generate_dataset(5, seed=1)[0].manifest_entry()
        != generate_dataset(5, seed=2)[0].manifest_entry()
    )


def test_committed_sample_and_examples_match_the_generator() -> None:
    manifest = json.loads((SAMPLE / "manifest.json").read_text())
    cases = sample_cases()
    assert manifest["cases"] == [case.manifest_entry() for case in cases]
    assert manifest["count"] == 12 and len(cases) == 12
    for case in cases:
        assert (SAMPLE / case.pdf_name).read_bytes() == case.pdf(), case.name
    assert Counter(case.document_type for case in cases) == {name: 4 for name in DOCUMENT_TYPES}
    assert sum(1 for case in cases if case.variant != "clean") == 6
    for filename, case in example_cases().items():
        assert (ROOT / "examples" / filename).read_bytes() == case.pdf(), filename


def test_write_and_ensure_generated_round_trip(tmp_path: Path) -> None:
    directory = tmp_path / "generated"
    assert ensure_generated(directory, count=6, seed=3) == directory
    manifest = directory / "manifest.json"
    stamp = manifest.stat().st_mtime_ns
    assert len(load_dataset(directory)) == 6
    ensure_generated(directory, count=6, seed=3)
    assert manifest.stat().st_mtime_ns == stamp
    ensure_generated(directory, count=4, seed=3)
    assert len(load_dataset(directory)) == 4 and len(list(directory.glob("*.pdf"))) == 4


def test_mock_eval_on_the_sample_reports_per_type_and_compares_to_baseline() -> None:
    cases = load_dataset(SAMPLE)
    router = ModelRouter(MockInvoiceProvider(recorder=lambda outcome: None))
    overall, by_type, failures = score_cases(router, cases)
    metrics = overall.metrics()
    expected = sum(len(case.truth) for case in cases)
    wrong = sum(len(case.should_flag) for case in cases)
    assert metrics["documents"] == 12 and set(by_type) == set(DOCUMENT_TYPES)
    assert metrics["type_detection"] == 1.0 and metrics["grounded_fraction"] == 1.0
    assert metrics["flag_recall"] == 1.0
    assert metrics["exact_match"] == round((expected - wrong) / expected, 4)
    assert not any(failure.get("type_mismatch") for failure in failures)
    assert not any(failure.get("missed_flag") for failure in failures)

    baseline = json.loads(BASELINE.read_text())
    assert set(baseline) == {*COMPARED_METRICS, "by_document_type"}
    assert set(baseline["by_document_type"]) == set(DOCUMENT_TYPES)
    assert compare_with_baseline(dict(baseline)) == []
    worse = {
        **baseline,
        "exact_match": baseline["exact_match"] - 0.05,
        "by_document_type": {
            **baseline["by_document_type"],
            "invoice": {"exact_match": 0.0, "type_detection": 1.0},
        },
    }
    problems = compare_with_baseline(worse)
    assert any(problem.startswith("exact_match") for problem in problems)
    assert any(problem.startswith("invoice.exact_match") for problem in problems)
    entry = baseline_entry(
        {**metrics, "by_document_type": {name: tally.metrics() for name, tally in by_type.items()}}
    )
    per_type = entry["by_document_type"]
    assert isinstance(per_type, dict)
    assert set(per_type["invoice"]) == {"exact_match", "type_detection"}
