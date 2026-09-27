"""The eval runner: cost accounting, the learning scenario and the written reports."""

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

from evals.run import (
    SAMPLE,
    Ledger,
    compare_with_baseline,
    learning_scenario,
    load_dataset,
    run,
    split_by_party,
)

from app.llm.client import CallOutcome
from app.llm.provider import MockInvoiceProvider
from app.llm.router import ModelRouter


def as_dict(value: object) -> dict[str, Any]:
    assert isinstance(value, dict)
    return dict(value)


def as_int(value: object) -> int:
    assert isinstance(value, int)
    return value


def outcome(cost: str | None, latency: int, ok: bool = True) -> CallOutcome:
    from datetime import UTC, datetime

    return CallOutcome(
        purpose="extraction",
        provider="mock",
        model="m",
        prompt_version="p",
        org_id=None,
        document_id=None,
        trace_id=None,
        tokens_in=10,
        tokens_out=5,
        cost_cents=Decimal(cost) if cost is not None else None,
        latency_ms=latency,
        ok=ok,
        error=None if ok else "boom",
        created_at=datetime.now(UTC),
    )


def test_ledger_summary_reports_cost_tokens_and_latency_percentiles() -> None:
    ledger = Ledger()
    for cost, latency, ok in (("1", 100, True), ("3", 300, True), (None, 200, False)):
        ledger.record(outcome(cost, latency, ok))
    summary = ledger.summary(documents=2)
    assert summary["calls"] == 3 and summary["failed_calls"] == 1
    assert summary["tokens_in"] == 30 and summary["tokens_out"] == 15
    assert summary["cost_cents_total"] == 4.0 and summary["cost_cents_per_document"] == 2.0
    assert summary["unpriced_calls"] == 1
    assert summary["latency_ms"] == {"mean": 200.0, "p50": 200, "p95": 300, "max": 300}
    assert Ledger().summary(documents=0)["cost_cents_per_document"] is None


def test_split_by_party_holds_out_half_of_each_vendor() -> None:
    cases = load_dataset(SAMPLE)
    train, held_out = split_by_party(cases)
    assert train and held_out
    assert {case.party for case in train} <= {case.party for case in held_out}
    assert not {case.name for case in train} & {case.name for case in held_out}
    assert len(train) + len(held_out) <= len(cases)


def test_learning_scenario_on_the_sample_does_not_regress_and_writes_memory() -> None:
    router = ModelRouter(MockInvoiceProvider(recorder=lambda outcome: None))
    report = learning_scenario(router, load_dataset(SAMPLE), strict=True)
    assert report["passed"] is True and report["regressions"] == []
    assert as_int(report["held_out_documents"]) > 0 and as_int(report["train_documents"]) > 0
    assert as_int(report["few_shots_written"]) >= 0
    after = as_dict(report["after"])
    assert after["fields_with_memory_prior"] > 0
    assert as_dict(report["deltas"])["exact_match"] >= 0.0


def test_run_writes_json_and_markdown_reports_with_cost_and_learning(tmp_path: Path) -> None:
    report = run("mock", tmp_path, SAMPLE, limit=8)
    assert report["provider"] == "mock" and report["prompt_version"] == "mock-v2"
    assert report["tier2_model"] is None and report["escalation_rate"] == 0.0
    cost = as_dict(report["cost"])
    assert cost["calls"] == 8 and cost["cost_cents_total"] == 0.0
    assert cost["cost_cents_per_document"] == 0.0 and cost["unpriced_calls"] == 0
    assert dict(cost["latency_ms"])["p95"] is not None
    written = sorted(tmp_path.iterdir())
    assert [path.suffix for path in written] == [".json", ".md"]
    stored = json.loads(written[0].read_text())
    assert stored["cost"] == report["cost"] and "learning" in stored
    markdown = written[1].read_text()
    assert "## Cost and latency" in markdown and "## Learning scenario" in markdown
    assert "Before memory | After memory" in markdown or "Not enough documents" in markdown
    assert compare_with_baseline({**report, "learning": {"passed": False, "regressions": ["x"]}})[
        -1
    ].startswith("learning: x")
