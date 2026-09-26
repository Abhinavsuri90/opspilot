"""Evaluate extraction against generated fictional text-layer invoices."""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from scripts.generate_demo_invoice import invoice_pdf

from app.config import get_settings
from app.llm.provider import ExtractionProvider, MockInvoiceProvider, OpenRouterInvoiceProvider


def run(provider_name: str, output_dir: Path) -> dict[str, object]:
    settings = get_settings()
    provider: ExtractionProvider
    if provider_name == "mock":
        provider = MockInvoiceProvider()
    else:
        if not settings.openrouter_api_key:
            raise RuntimeError(
                "Set OPENROUTER_API_KEY locally before running a live model eval"
            )
        provider = OpenRouterInvoiceProvider(
            settings.openrouter_api_key, settings.openrouter_model
        )

    correct = 0
    grounded = 0
    expected_count = 0
    failures: list[dict[str, object]] = []
    for number in range(1, 21):
        truth = {
            "vendor": "Northwind Traders" if number % 2 else "Contoso Logistics",
            "invoice_number": f"EVAL-{number:04d}",
            "invoice_date": f"2026-09-{number:02d}",
            "total": f"${number * 17 + 0.45:.2f}",
        }
        data = invoice_pdf(
            invoice_number=truth["invoice_number"],
            vendor=truth["vendor"],
            invoice_date=truth["invoice_date"],
            total=truth["total"],
        )
        expected_count += len(truth)
        try:
            fields = provider.extract(data)
        except Exception as exc:
            failures.append({"invoice": number, "error_type": type(exc).__name__})
            continue
        predicted = {field.name: field for field in fields}
        for name, value in truth.items():
            field = predicted.get(name)
            if field is not None and field.value == value:
                correct += 1
            else:
                failures.append({"invoice": number, "field": name})
            if (
                field is not None
                and field.value in field.evidence
                and field.page_number == 1
            ):
                grounded += 1

    report: dict[str, object] = {
        "dataset": "20 generated fictional text-layer invoices",
        "provider": provider.name,
        "model": provider.model,
        "documents": 20,
        "fields_expected": expected_count,
        "exact_match": round(correct / expected_count, 4),
        "grounded_fraction": round(grounded / expected_count, 4),
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
        f"# Synthetic invoice eval — {provider_name}\n\n"
        f"Model: `{provider.model}`  \n"
        f"Documents: 20  \n"
        f"Exact field match: {report['exact_match']:.1%}  \n"
        f"Grounded fields: {report['grounded_fraction']:.1%}\n\n"
        f"{report['limitations']}\n"
    )
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", choices=("mock", "openrouter"), default="mock")
    parser.add_argument(
        "--output-dir", type=Path, default=Path("/workspace/evals/reports")
    )
    args = parser.parse_args()
    result = run(args.provider, args.output_dir)
    print(
        json.dumps(
            {
                key: result[key]
                for key in ("provider", "model", "exact_match", "grounded_fraction")
            }
        )
    )
    if args.provider == "mock" and cast(float, result["exact_match"]) < 0.98:
        raise SystemExit("Mock extraction regressed below the 98% synthetic baseline")
