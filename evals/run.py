"""Evaluate extraction, flagging, document-type detection, cost and learning on synthetic data.

Datasets come from ``scripts/generate_synthetic.py``: a deterministic, gitignored set of 150
documents (generated on demand into ``evals/datasets/generated``) and a committed sample of
12 under ``evals/datasets/sample``. Each case carries the intended values and the fields a
reviewer should be asked about; the confidence engine's needs_review decision is scored
against that as precision and recall, per document type and overall.

Every document goes through the production path (``ModelRouter`` over the provider, with
tier 2 when ``LLM_TIER2_MODEL`` is set for OpenRouter), with an in-memory ledger recorder so
the report can state tokens, cost and latency exactly as the worker would have logged them.

The learning scenario splits each vendor's documents into a training half and a held-out
half, scores the held-out half cold, ingests the training half's ground truth as reviewer
corrections into an isolated in-memory copy of ``memory_items``, scores the held-out half
again with that memory, and asserts that accuracy did not regress. With the mock provider
memory only feeds the ``memory_prior`` signal (the deterministic extractor cannot read
examples), so the scenario proves the plumbing and the no-regression guarantee; the real
learning effect is measured on the live-model subset.
"""

import argparse
import json
import statistics
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from app import memory
from app.config import get_settings
from app.llm.client import CallOutcome
from app.llm.embeddings import LocalHashEmbedder
from app.llm.provider import (
    ExtractionContext,
    ExtractionProvider,
    MockInvoiceProvider,
    OpenRouterInvoiceProvider,
    pdf_pages,
)
from app.llm.router import Assessment, ModelRouter
from app.models import Base
from app.workflow_config import template_config
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from scripts.generate_synthetic import (
    DEFAULT_COUNT,
    DEFAULT_SEED,
    generate_dataset,
    write_dataset,
)

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
# A fixed tenant id for the in-memory ledger and memory store; never a real organization.
EVAL_ORG = uuid.UUID("00000000-0000-4000-8000-0000000e7a10")
LEARNING_METRICS = ("exact_match", "flag_recall", "flag_precision")


@dataclass
class Case:
    name: str
    document_type: str
    template: str
    pdf: bytes
    truth: dict[str, str]
    # Fields whose printed value is deliberately wrong or absent.
    should_flag: set[str] = field(default_factory=set)

    @property
    def party(self) -> str | None:
        return self.truth.get("vendor") or self.truth.get("supplier")


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
    escalated: int = 0
    with_prior: int = 0

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
            "escalation_rate": (
                round(self.escalated / self.documents, 4) if self.documents else 0.0
            ),
            "fields_with_memory_prior": self.with_prior,
            "flag_counts": {
                "true_positive": self.true_positive,
                "false_positive": self.false_positive,
                "false_negative": self.false_negative,
            },
        }


@dataclass
class Ledger:
    """In-memory stand-in for ``llm_calls``: the same rows the worker would have written."""

    calls: list[CallOutcome] = field(default_factory=list)

    def record(self, outcome: CallOutcome) -> None:
        self.calls.append(outcome)

    def summary(self, documents: int) -> dict[str, object]:
        priced = [call.cost_cents for call in self.calls if call.cost_cents is not None]
        total = sum(priced, Decimal("0.0000"))
        latencies = sorted(call.latency_ms for call in self.calls)
        return {
            "calls": len(self.calls),
            "failed_calls": sum(1 for call in self.calls if not call.ok),
            "tokens_in": sum(call.tokens_in or 0 for call in self.calls),
            "tokens_out": sum(call.tokens_out or 0 for call in self.calls),
            "cost_cents_total": float(total),
            "cost_cents_per_document": (
                round(float(total) / documents, 4) if documents and priced else None
            ),
            "unpriced_calls": len(self.calls) - len(priced),
            "latency_ms": {
                "mean": round(statistics.fmean(latencies), 1) if latencies else None,
                "p50": _percentile(latencies, 0.5),
                "p95": _percentile(latencies, 0.95),
                "max": latencies[-1] if latencies else None,
            },
        }


def _percentile(values: list[int], fraction: float) -> int | None:
    if not values:
        return None
    index = min(len(values) - 1, max(0, round(fraction * (len(values) - 1))))
    return values[index]


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


def make_providers(
    provider_name: str, ledger: Ledger
) -> tuple[ExtractionProvider, ExtractionProvider | None]:
    """The tier-1 provider and, for OpenRouter with LLM_TIER2_MODEL, the tier-2 provider."""
    settings = get_settings()
    if provider_name == "mock":
        return MockInvoiceProvider(recorder=ledger.record), None
    if not settings.openrouter_api_key:
        raise RuntimeError("Set OPENROUTER_API_KEY locally before running a live model eval")
    tier1 = OpenRouterInvoiceProvider(
        settings.openrouter_api_key,
        settings.llm_tier1_model or settings.openrouter_model,
        recorder=ledger.record,
    )
    tier2 = (
        OpenRouterInvoiceProvider(
            settings.openrouter_api_key, settings.llm_tier2_model, recorder=ledger.record
        )
        if settings.llm_tier2_model
        else None
    )
    return tier1, tier2


def assess_case(
    router: ModelRouter, case: Case, memory_session: Session | None = None
) -> Assessment:
    config = template_config(case.template)
    pages = pdf_pages(case.pdf)
    context = ExtractionContext(EVAL_ORG, None, case.name)
    memory_context = None
    if memory_session is not None:
        memory_context = memory.context_for(
            memory_session, EVAL_ORG, pages, config, embedder=LocalHashEmbedder()
        )
    return router.run(pages, config, context, memory_context)


def score_cases(
    router: ModelRouter, cases: list[Case], memory_session: Session | None = None
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
            assessment = assess_case(router, case, memory_session)
        except Exception as exc:  # noqa: BLE001 - evaluation records every case failure
            failures.append({"case": case.name, "error_type": type(exc).__name__})
            for tally in tallies:
                tally.false_negative += len(case.should_flag)
            continue
        result, evaluation = assessment.result, assessment.evaluation
        if result.document_type == case.document_type:
            for tally in tallies:
                tally.detected += 1
        else:
            failures.append(
                {"case": case.name, "detected_type": result.document_type, "type_mismatch": True}
            )
        for tally in tallies:
            tally.escalated += 1 if assessment.escalated else 0
            tally.with_prior += sum(
                1 for value in assessment.memory_prior.values() if value is not None
            )
        predicted = {item.name: item for item in result.fields}
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


def split_by_party(cases: list[Case]) -> tuple[list[Case], list[Case]]:
    """Per vendor, the first half of its documents trains and the rest is held out."""
    by_party: dict[str, list[Case]] = {}
    for case in cases:
        if case.party:
            by_party.setdefault(case.party, []).append(case)
    train: list[Case] = []
    held_out: list[Case] = []
    for _, group in sorted(by_party.items()):
        if len(group) < 2:
            continue
        group = sorted(group, key=lambda item: item.name)
        half = len(group) // 2
        train.extend(group[:half])
        held_out.extend(group[half:])
    return train, held_out


def memory_store() -> Session:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return Session(engine)


def ingest_truth(session: Session, router: ModelRouter, cases: list[Case]) -> int:
    """Apply the ground truth of each training case as reviewer corrections into memory."""
    written = 0
    for case in cases:
        config = template_config(case.template)
        type_spec = config.document_type(case.document_type)
        assert type_spec is not None and case.party
        try:
            assessment = assess_case(router, case)
            extracted = {item.name: item for item in assessment.result.fields}
        except Exception:  # noqa: BLE001 - missing predictions become corrections
            extracted = {}
        corrections = [
            memory.Correction(
                name,
                extracted[name].value if name in extracted else "",
                truth,
                extracted[name].evidence if name in extracted else f"{name}: {truth}",
            )
            for name, truth in case.truth.items()
            if name not in extracted or extracted[name].value != truth
        ]
        _, count = memory.learn(
            session,
            EVAL_ORG,
            vendor=case.party,
            type_spec=type_spec,
            values=case.truth,
            corrections=corrections,
            embedder=LocalHashEmbedder(),
            trace_id=case.name,
        )
        written += count
    session.commit()
    return written


def learning_scenario(router: ModelRouter, cases: list[Case], strict: bool) -> dict[str, object]:
    """Score held-out documents cold, ingest the training half, score again with memory."""
    train, held_out = split_by_party(cases)
    if not train or not held_out:
        return {"skipped": "Not enough documents per vendor to hold some out"}
    before, _, _ = score_cases(router, held_out)
    with memory_store() as session:
        few_shots = ingest_truth(session, router, train)
        after, _, _ = score_cases(router, held_out, session)
    before_metrics, after_metrics = before.metrics(), after.metrics()
    deltas = {
        metric: round(float(str(after_metrics[metric])) - float(str(before_metrics[metric])), 4)
        for metric in LEARNING_METRICS
    }
    tolerance = 0.0 if strict else TOLERANCE
    regressions = []
    for metric in ("exact_match", "flag_recall"):
        current, previous = float(str(after_metrics[metric])), float(str(before_metrics[metric]))
        if current < previous - tolerance:
            regressions.append(f"{metric}: {current:.4f} < {previous:.4f}")
    return {
        "train_documents": len(train),
        "held_out_documents": len(held_out),
        "vendors": len({case.party for case in train}),
        "few_shots_written": few_shots,
        "before": {metric: before_metrics[metric] for metric in LEARNING_METRICS},
        "after": {
            **{metric: after_metrics[metric] for metric in LEARNING_METRICS},
            "fields_with_memory_prior": after_metrics["fields_with_memory_prior"],
        },
        "deltas": deltas,
        "regressions": regressions,
        "passed": not regressions,
    }


def run(
    provider_name: str, output_dir: Path, dataset_dir: Path, limit: int | None = None
) -> dict[str, object]:
    ledger = Ledger()
    tier1, tier2 = make_providers(provider_name, ledger)
    router = ModelRouter(tier1, tier2)
    cases = load_dataset(dataset_dir)
    if limit is not None:
        cases = cases[:limit]
    overall, by_type, failures = score_cases(router, cases)
    cost = ledger.summary(len(cases))
    learning = learning_scenario(router, cases, strict=provider_name == "mock")
    perturbed = sum(1 for case in cases if case.should_flag)
    report: dict[str, object] = {
        "dataset": (
            f"{len(cases)} synthetic text-layer documents from {dataset_dir.name} "
            f"({perturbed} perturbed; types: {', '.join(sorted(by_type))})"
        ),
        "provider": tier1.name,
        "model": tier1.model,
        "tier2_model": tier2.model if tier2 is not None else None,
        "prompt_version": tier1.prompt_version,
        **overall.metrics(),
        "cost": cost,
        "learning": learning,
        "by_document_type": {name: tally.metrics() for name, tally in sorted(by_type.items())},
        "failures": failures,
        "limitations": (
            "Synthetic text-layer documents only; these results do not measure scanned PDFs, "
            "real customer documents, or human-review quality. Cost and latency are for the "
            "main pass only (the learning scenario's calls are excluded)."
        ),
    }
    write_reports(report, output_dir, provider_name, tier1, by_type, len(cases))
    return report


def _pct(value: object) -> str:
    return f"{float(str(value)):.1%}"


def write_reports(
    report: dict[str, object],
    output_dir: Path,
    provider_name: str,
    provider: ExtractionProvider,
    by_type: dict[str, Tally],
    documents: int,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    stem = f"{timestamp}-{provider_name}"
    (output_dir / f"{stem}.json").write_text(json.dumps(report, indent=2) + "\n")
    cost = dict(report["cost"]) if isinstance(report["cost"], dict) else {}
    latency = dict(cost.get("latency_ms") or {})
    learning = dict(report["learning"]) if isinstance(report["learning"], dict) else {}
    lines = [
        f"# Synthetic document eval: {provider_name}",
        "",
        f"Model: `{provider.model}` (tier 2: `{report['tier2_model'] or 'none'}`)  ",
        f"Prompt: `{report['prompt_version']}`  ",
        f"Documents: {documents}  ",
        f"Exact field match: {_pct(report['exact_match'])}  ",
        f"Grounded fields: {_pct(report['grounded_fraction'])}  ",
        f"Flagging precision: {_pct(report['flag_precision'])}  ",
        f"Flagging recall: {_pct(report['flag_recall'])}  ",
        f"Type detection: {_pct(report['type_detection'])}  ",
        f"Escalation rate: {_pct(report['escalation_rate'])}",
        "",
        "## Cost and latency",
        "",
        f"Model calls: {cost.get('calls')} ({cost.get('failed_calls')} failed, "
        + f"{cost.get('unpriced_calls')} unpriced)  ",
        f"Tokens: {cost.get('tokens_in')} in / {cost.get('tokens_out')} out  ",
        f"Cost: {cost.get('cost_cents_total')} cents total, "
        + f"{cost.get('cost_cents_per_document')} cents per document  ",
        f"Latency (ms): mean {latency.get('mean')}, p50 {latency.get('p50')}, "
        + f"p95 {latency.get('p95')}, max {latency.get('max')}",
        "",
        "## Learning scenario",
        "",
    ]
    if "skipped" in learning:
        lines.append(str(learning["skipped"]))
    else:
        before = dict(learning["before"])
        after = dict(learning["after"])
        lines += [
            f"Trained on {learning['train_documents']} documents from {learning['vendors']} "
            + f"vendors ({learning['few_shots_written']} few-shot examples); "
            + f"held out {learning['held_out_documents']}.",
            "",
            "| Metric | Before memory | After memory | Delta |",
            "|---|---:|---:|---:|",
        ]
        for metric in LEARNING_METRICS:
            lines.append(
                f"| {metric} | {_pct(before[metric])} | {_pct(after[metric])} | "
                f"{float(str(dict(learning['deltas'])[metric])):+.4f} |"
            )
        lines.append("")
        lines.append(
            "Result: " + ("no regression" if learning["passed"] else "REGRESSED") + "; "
            f"{after['fields_with_memory_prior']} held-out fields carried a memory prior."
        )
    lines += [
        "",
        "## By document type",
        "",
        "| Document type | Documents | Exact match | Flag precision | Flag recall | Detection |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for name, tally in sorted(by_type.items()):
        metrics = tally.metrics()
        lines.append(
            f"| {name} | {metrics['documents']} | {_pct(metrics['exact_match'])} | "
            f"{_pct(metrics['flag_precision'])} | {_pct(metrics['flag_recall'])} | "
            f"{_pct(metrics['type_detection'])} |"
        )
    lines += ["", str(report["limitations"]), ""]
    (output_dir / f"{stem}.md").write_text("\n".join(lines))


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
    learning = report.get("learning")
    if isinstance(learning, dict) and learning.get("passed") is False:
        regressions.append("learning: " + "; ".join(str(item) for item in learning["regressions"]))
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
        "--limit", type=int, default=None, help="Score only the first N documents (live runs)"
    )
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
    result = run(args.provider, args.output_dir, directory, args.limit)
    summary = {key: result[key] for key in ("provider", "model", *COMPARED_METRICS)}
    summary["cost"] = result["cost"]
    summary["learning"] = result["learning"]
    print(json.dumps(summary))
    if args.provider == "mock":
        if args.update_baseline:
            BASELINE.write_text(json.dumps(baseline_entry(result), indent=2) + "\n")
        else:
            problems = compare_with_baseline(result)
            if problems:
                raise SystemExit("Mock extraction regressed: " + "; ".join(problems))
    else:
        learning = result["learning"]
        if isinstance(learning, dict) and learning.get("passed") is False:
            raise SystemExit("Live model learning scenario regressed: " + str(learning))
