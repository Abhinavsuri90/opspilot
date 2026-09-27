"""Evaluate extraction and flagging against generated fictional text-layer invoices.

The dataset is deterministic: 20 clean invoices plus perturbed cases whose printed
values are wrong or missing. A field whose extracted value differs from the intended
truth "should flag"; the confidence engine's needs_review decision is scored against
that as precision and recall.
"""

import argparse
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from scripts.generate_demo_invoice import invoice_pdf

from app.confidence import evaluate
from app.config import get_settings
from app.llm.provider import ExtractionProvider, MockInvoiceProvider, OpenRouterInvoiceProvider
from app.workflow_config import default_invoice_config

BASELINE = Path(__file__).with_name("baseline.json")
TOLERANCE = 0.02
COMPARED_METRICS = ("exact_match", "grounded_fraction", "flag_precision", "flag_recall")


@dataclass
class Case:
    name: str
    pdf: bytes
    truth: dict[str, str]
    # Fields whose printed value is deliberately wrong or absent.
    should_flag: set[str] = field(default_factory=set)


def clean_cases() -> list[Case]:
    cases = []
    for number in range(1, 21):
        truth = {
            "vendor": "Northwind Traders" if number % 2 else "Contoso Logistics",
            "invoice_number": f"EVAL-{number:04d}",
            "invoice_date": f"2026-09-{number:02d}",
            "total": f"${number * 17 + 0.45:.2f}",
        }
        cases.append(
            Case(
                f"clean-{number:02d}",
                invoice_pdf(
                    invoice_number=truth["invoice_number"],
                    vendor=truth["vendor"],
                    invoice_date=truth["invoice_date"],
                    total=truth["total"],
                ),
                truth,
            )
        )
    return cases


def _pdf(
    truth: dict[str, str],
    *,
    printed: dict[str, str] | None = None,
    extra_lines: dict[str, str] | None = None,
    omit: tuple[str, ...] = (),
) -> bytes:
    shown = truth | (printed or {})
    return invoice_pdf(
        invoice_number=shown["invoice_number"],
        vendor=shown["vendor"],
        invoice_date=shown["invoice_date"],
        total=shown["total"],
        extra_lines=extra_lines,
        omit=omit,
    )


def perturbed_cases() -> list[Case]:
    base = {
        "vendor": "Harbor Supply Co",
        "invoice_number": "EVAL-P-001",
        "invoice_date": "2026-09-05",
        "total": "$110.00",
    }
    lines = {"Subtotal": "$100.00", "Tax": "$10.00"}
    with_lines = base | {"subtotal": "$100.00", "tax": "$10.00"}
    return [
        Case("mangled-total", _pdf(base, printed={"total": "$11O.OO"}), base, {"total"}),
        Case(
            "mangled-date",
            _pdf(base, printed={"invoice_date": "2026-09-31"}),
            base,
            {"invoice_date"},
        ),
        Case("missing-vendor", _pdf(base, omit=("Vendor",)), base, {"vendor"}),
        Case("totals-add-up", _pdf(base, extra_lines=lines), with_lines),
        Case(
            "wrong-total-for-lines",
            _pdf(base, printed={"total": "$120.00"}, extra_lines=lines),
            with_lines,
            {"total"},
        ),
        Case(
            "lowercase-currency",
            _pdf(base, extra_lines={"Currency": "usd", "Due Date": "2026-10-05"}),
            base | {"currency": "USD", "due_date": "2026-10-05"},
            {"currency"},
        ),
        Case(
            "due-before-issue",
            _pdf(base, extra_lines={"Due Date": "2026-08-01"}),
            base | {"due_date": "2026-09-30"},
            {"due_date"},
        ),
    ]


def run(provider_name: str, output_dir: Path) -> dict[str, object]:
    settings = get_settings()
    provider: ExtractionProvider
    if provider_name == "mock":
        provider = MockInvoiceProvider()
    else:
        if not settings.openrouter_api_key:
            raise RuntimeError("Set OPENROUTER_API_KEY locally before running a live model eval")
        provider = OpenRouterInvoiceProvider(settings.openrouter_api_key, settings.openrouter_model)

    config = default_invoice_config()
    type_spec = config.document_types[0]
    cases = clean_cases() + perturbed_cases()
    expected = correct = predicted_count = grounded = 0
    true_positive = false_positive = false_negative = 0
    failures: list[dict[str, object]] = []
    for case in cases:
        expected += len(case.truth)
        try:
            result = provider.extract(case.pdf, config)
        except Exception as exc:
            failures.append({"case": case.name, "error_type": type(exc).__name__})
            false_negative += len(case.should_flag)
            continue
        predicted = {item.name: item for item in result.fields}
        evaluation = evaluate(result.fields, result.pages, type_spec)
        assessed = {item.name: item for item in evaluation.fields}
        for name, expected_value in case.truth.items():
            extracted = predicted.get(name)
            mismatch = extracted is None or extracted.value != expected_value
            if mismatch:
                failures.append({"case": case.name, "field": name})
            else:
                correct += 1
            flagged = name in assessed and assessed[name].status == "needs_review"
            should_flag = name in case.should_flag or mismatch
            if flagged and should_flag:
                true_positive += 1
            elif flagged:
                false_positive += 1
                failures.append({"case": case.name, "field": name, "unexpected_flag": True})
            elif should_flag:
                false_negative += 1
                failures.append({"case": case.name, "field": name, "missed_flag": True})
        for item in result.fields:
            predicted_count += 1
            on_page = 0 < item.page_number <= len(result.pages)
            page = result.pages[item.page_number - 1] if on_page else ""
            if item.evidence in page and item.value in item.evidence:
                grounded += 1

    flagged_total = true_positive + false_positive
    should_total = true_positive + false_negative
    report: dict[str, object] = {
        "dataset": f"{len(cases)} generated fictional text-layer invoices "
        f"({len(perturbed_cases())} perturbed)",
        "provider": provider.name,
        "model": provider.model,
        "documents": len(cases),
        "fields_expected": expected,
        "fields_predicted": predicted_count,
        "exact_match": round(correct / expected, 4),
        "grounded_fraction": round(grounded / predicted_count, 4) if predicted_count else 0.0,
        "flag_precision": round(true_positive / flagged_total, 4) if flagged_total else 1.0,
        "flag_recall": round(true_positive / should_total, 4) if should_total else 1.0,
        "flag_counts": {
            "true_positive": true_positive,
            "false_positive": false_positive,
            "false_negative": false_negative,
        },
        "failures": failures,
        "limitations": (
            "Synthetic text-layer invoices only; these results do not measure scanned PDFs, "
            "real customer documents, or human-review quality."
        ),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    stem = f"{timestamp}-{provider_name}"
    (output_dir / f"{stem}.json").write_text(json.dumps(report, indent=2) + "\n")
    (output_dir / f"{stem}.md").write_text(
        f"# Synthetic invoice eval: {provider_name}\n\n"
        f"Model: `{provider.model}`  \n"
        f"Documents: {len(cases)}  \n"
        f"Exact field match: {report['exact_match']:.1%}  \n"
        f"Grounded fields: {report['grounded_fraction']:.1%}  \n"
        f"Flagging precision: {report['flag_precision']:.1%}  \n"
        f"Flagging recall: {report['flag_recall']:.1%}\n\n"
        f"{report['limitations']}\n"
    )
    return report


def compare_with_baseline(report: dict[str, object]) -> list[str]:
    """Metrics that regressed by more than the tolerance against evals/baseline.json."""
    if not BASELINE.exists():
        return [f"Baseline file {BASELINE} is missing; run with --update-baseline"]
    baseline = json.loads(BASELINE.read_text())
    regressions = []
    for metric in COMPARED_METRICS:
        current, expected = float(str(report[metric])), float(str(baseline[metric]))
        if current < expected - TOLERANCE:
            regressions.append(f"{metric}: {current:.4f} is below baseline {expected:.4f}")
    return regressions


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", choices=("mock", "openrouter"), default="mock")
    parser.add_argument("--output-dir", type=Path, default=Path("/workspace/evals/reports"))
    parser.add_argument(
        "--update-baseline",
        action="store_true",
        help="Rewrite evals/baseline.json from this mock run instead of comparing",
    )
    args = parser.parse_args()
    result = run(args.provider, args.output_dir)
    print(json.dumps({key: result[key] for key in ("provider", "model", *COMPARED_METRICS)}))
    if args.provider == "mock":
        if args.update_baseline:
            BASELINE.write_text(
                json.dumps({key: result[key] for key in COMPARED_METRICS}, indent=2) + "\n"
            )
        else:
            problems = compare_with_baseline(result)
            if problems:
                raise SystemExit("Mock extraction regressed: " + "; ".join(problems))
