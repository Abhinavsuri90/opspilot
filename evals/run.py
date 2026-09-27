"""Evaluate extraction, flagging and document-type detection on synthetic datasets.

Datasets come from ``scripts/generate_synthetic.py``: a deterministic, gitignored set of 150
documents (generated on demand into ``evals/datasets/generated``) and a committed sample of
12 under ``evals/datasets/sample``. Each case carries the intended values and the fields a
reviewer should be asked about; the confidence engine's needs_review decision is scored
against that as precision and recall, per document type and overall.
"""

import argparse
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from scripts.generate_synthetic import DEFAULT_COUNT, DEFAULT_SEED, generate_dataset, write_dataset

from app.confidence import evaluate
from app.config import get_settings
from app.llm.provider import ExtractionProvider, MockInvoiceProvider, OpenRouterInvoiceProvider
from app.workflow_config import template_config

DATASETS = Path(__file__).with_name("datasets")
GENERATED = DATASETS / "generated"
SAMPLE = DATASETS / "sample"
BASELINE = Path(__file__).with_name("baseline.json")
TOLERANCE = 0.02
COMPARED_METRICS = (
    "exact_match",
    "grounded_fraction",
    "flag_precision",
    "flag_recall",
    "type_detection",
)


@dataclass
class Case:
    name: str
    document_type: str
    template: str
    pdf: bytes
    truth: dict[str, str]
    # Fields whose printed value is deliberately wrong or absent.
    should_flag: set[str] = field(default_factory=set)


@dataclass
class Tally:
    documents: int = 0
    expected: int = 0
    correct: int = 0
    predicted: int = 0
    grounded: int = 0
    true_positive: int = 0
    false_positive: int = 0
    false_negative: int = 0
    detected: int = 0

    def metrics(self) -> dict[str, object]:
        flagged = self.true_positive + self.false_positive
        should = self.true_positive + self.false_negative
        return {
            "documents": self.documents,
            "fields_expected": self.expected,
            "fields_predicted": self.predicted,
            "exact_match": round(self.correct / self.expected, 4) if self.expected else 0.0,
            "grounded_fraction": (
                round(self.grounded / self.predicted, 4) if self.predicted else 0.0
            ),
            "flag_precision": round(self.true_positive / flagged, 4) if flagged else 1.0,
            "flag_recall": round(self.true_positive / should, 4) if should else 1.0,
            "type_detection": (round(self.detected / self.documents, 4) if self.documents else 0.0),
            "flag_counts": {
                "true_positive": self.true_positive,
                "false_positive": self.false_positive,
                "false_negative": self.false_negative,
            },
        }


def ensure_generated(
    directory: Path = GENERATED, count: int = DEFAULT_COUNT, seed: int = DEFAULT_SEED
) -> Path:
    """Generate the dataset when it is missing or was made with other parameters."""
    manifest = directory / "manifest.json"
    if manifest.exists():
        stored = json.loads(manifest.read_text())
        if stored.get("seed") == seed and stored.get("count") == count:
            return directory
    write_dataset(generate_dataset(count, seed), directory, seed)
    return directory


def load_dataset(directory: Path) -> list[Case]:
    manifest = json.loads((directory / "manifest.json").read_text())
    cases = []
    for entry in manifest["cases"]:
        cases.append(
            Case(
                name=str(entry["name"]),
                document_type=str(entry["document_type"]),
                template=str(entry["template"]),
                pdf=(directory / str(entry["pdf"])).read_bytes(),
                truth={str(k): str(v) for k, v in dict(entry["truth"]).items()},
                should_flag={str(item) for item in entry.get("should_flag", [])},
            )
        )
    return cases


def score_cases(
    provider: ExtractionProvider, cases: list[Case]
) -> tuple[Tally, dict[str, Tally], list[dict[str, object]]]:
    overall = Tally()
    by_type: dict[str, Tally] = {}
    failures: list[dict[str, object]] = []
    for case in cases:
        config = template_config(case.template)
        type_spec = config.document_type(case.document_type)
        assert type_spec is not None
        tallies = (overall, by_type.setdefault(case.document_type, Tally()))
        for tally in tallies:
            tally.documents += 1
            tally.expected += len(case.truth)
        try:
            result = provider.extract(case.pdf, config)
        except Exception as exc:
            failures.append({"case": case.name, "error_type": type(exc).__name__})
            for tally in tallies:
                tally.false_negative += len(case.should_flag)
            continue
        if result.document_type == case.document_type:
            for tally in tallies:
                tally.detected += 1
        else:
            failures.append(
                {"case": case.name, "detected_type": result.document_type, "type_mismatch": True}
            )
        predicted = {item.name: item for item in result.fields}
        evaluation = evaluate(result.fields, result.pages, type_spec)
        assessed = {item.name: item for item in evaluation.fields}
        for name, expected_value in case.truth.items():
            extracted = predicted.get(name)
            mismatch = extracted is None or extracted.value != expected_value
            if mismatch:
                failures.append({"case": case.name, "field": name})
            flagged = name in assessed and assessed[name].status == "needs_review"
            should_flag = name in case.should_flag or mismatch
            for tally in tallies:
                if not mismatch:
                    tally.correct += 1
                if flagged and should_flag:
                    tally.true_positive += 1
                elif flagged:
                    tally.false_positive += 1
                elif should_flag:
                    tally.false_negative += 1
            if flagged and not should_flag:
                failures.append({"case": case.name, "field": name, "unexpected_flag": True})
            elif should_flag and not flagged:
                failures.append({"case": case.name, "field": name, "missed_flag": True})
        for item in result.fields:
            on_page = 0 < item.page_number <= len(result.pages)
            page = result.pages[item.page_number - 1] if on_page else ""
            grounded = item.evidence in page and item.value in item.evidence
            for tally in tallies:
                tally.predicted += 1
                if grounded:
                    tally.grounded += 1
    return overall, by_type, failures


def run(provider_name: str, output_dir: Path, dataset_dir: Path) -> dict[str, object]:
    settings = get_settings()
    provider: ExtractionProvider
    if provider_name == "mock":
        provider = MockInvoiceProvider()
    else:
        if not settings.openrouter_api_key:
            raise RuntimeError("Set OPENROUTER_API_KEY locally before running a live model eval")
        provider = OpenRouterInvoiceProvider(settings.openrouter_api_key, settings.openrouter_model)

    cases = load_dataset(dataset_dir)
    overall, by_type, failures = score_cases(provider, cases)
    perturbed = sum(1 for case in cases if case.should_flag)
    report: dict[str, object] = {
        "dataset": (
            f"{len(cases)} synthetic text-layer documents from {dataset_dir.name} "
            f"({perturbed} perturbed; types: {', '.join(sorted(by_type))})"
        ),
        "provider": provider.name,
        "model": provider.model,
        **overall.metrics(),
        "by_document_type": {name: tally.metrics() for name, tally in sorted(by_type.items())},
        "failures": failures,
        "limitations": (
            "Synthetic text-layer documents only; these results do not measure scanned PDFs, "
            "real customer documents, or human-review quality."
        ),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    stem = f"{timestamp}-{provider_name}"
    (output_dir / f"{stem}.json").write_text(json.dumps(report, indent=2) + "\n")
    lines = [
        f"# Synthetic document eval: {provider_name}",
        "",
        f"Model: `{provider.model}`  ",
        f"Documents: {len(cases)}  ",
        f"Exact field match: {float(str(report['exact_match'])):.1%}  ",
        f"Grounded fields: {float(str(report['grounded_fraction'])):.1%}  ",
        f"Flagging precision: {float(str(report['flag_precision'])):.1%}  ",
        f"Flagging recall: {float(str(report['flag_recall'])):.1%}  ",
        f"Type detection: {float(str(report['type_detection'])):.1%}",
        "",
        "| Document type | Documents | Exact match | Flag precision | Flag recall | Detection |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for name, tally in sorted(by_type.items()):
        metrics = tally.metrics()
        lines.append(
            f"| {name} | {metrics['documents']} | {float(str(metrics['exact_match'])):.1%} | "
            f"{float(str(metrics['flag_precision'])):.1%} | "
            f"{float(str(metrics['flag_recall'])):.1%} | "
            f"{float(str(metrics['type_detection'])):.1%} |"
        )
    lines += ["", str(report["limitations"]), ""]
    (output_dir / f"{stem}.md").write_text("\n".join(lines))
    return report


def baseline_entry(report: dict[str, object]) -> dict[str, object]:
    by_type = report.get("by_document_type")
    return {
        **{key: report[key] for key in COMPARED_METRICS},
        "by_document_type": {
            name: {
                "exact_match": metrics["exact_match"],
                "type_detection": metrics["type_detection"],
            }
            for name, metrics in (by_type.items() if isinstance(by_type, dict) else [])
        },
    }


def compare_with_baseline(report: dict[str, object]) -> list[str]:
    """Metrics that regressed by more than the tolerance against evals/baseline.json."""
    if not BASELINE.exists():
        return [f"Baseline file {BASELINE} is missing; run with --update-baseline"]
    baseline = json.loads(BASELINE.read_text())
    regressions = []
    for metric in COMPARED_METRICS:
        if metric not in baseline:
            continue
        current, expected = float(str(report[metric])), float(str(baseline[metric]))
        if current < expected - TOLERANCE:
            regressions.append(f"{metric}: {current:.4f} is below baseline {expected:.4f}")
    current_types = report.get("by_document_type")
    for name, expected_metrics in dict(baseline.get("by_document_type", {})).items():
        if not isinstance(current_types, dict) or name not in current_types:
            regressions.append(f"{name}: missing from the current run")
            continue
        for metric, expected in dict(expected_metrics).items():
            current = float(str(current_types[name][metric]))
            if current < float(str(expected)) - TOLERANCE:
                regressions.append(
                    f"{name}.{metric}: {current:.4f} is below baseline {float(str(expected)):.4f}"
                )
    return regressions


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", choices=("mock", "openrouter"), default="mock")
    parser.add_argument("--output-dir", type=Path, default=Path("/workspace/evals/reports"))
    parser.add_argument(
        "--dataset",
        choices=("generated", "sample"),
        default="generated",
        help="generated: 150 deterministic documents (built on demand); sample: the 12 committed",
    )
    parser.add_argument("--count", type=int, default=DEFAULT_COUNT)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument(
        "--update-baseline",
        action="store_true",
        help="Rewrite evals/baseline.json from this mock run instead of comparing",
    )
    args = parser.parse_args()
    if args.dataset == "generated":
        directory = ensure_generated(GENERATED, args.count, args.seed)
    else:
        directory = SAMPLE
    result = run(args.provider, args.output_dir, directory)
    print(json.dumps({key: result[key] for key in ("provider", "model", *COMPARED_METRICS)}))
    if args.provider == "mock":
        if args.update_baseline:
            BASELINE.write_text(json.dumps(baseline_entry(result), indent=2) + "\n")
        else:
            problems = compare_with_baseline(result)
            if problems:
                raise SystemExit("Mock extraction regressed: " + "; ".join(problems))
