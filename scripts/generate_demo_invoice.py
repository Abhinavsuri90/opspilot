"""Generate a small, text-layer PDF containing fictional invoice data."""

import argparse
from pathlib import Path

from scripts.generate_synthetic import render_pdf


def invoice_pdf(
    invoice_number: str = "NW-2026-001",
    vendor: str = "Northwind Traders",
    invoice_date: str = "2026-09-26",
    total: str = "$123.45",
    extra_lines: dict[str, str] | None = None,
    omit: tuple[str, ...] = (),
) -> bytes:
    """Build a one-page text invoice.

    ``extra_lines`` adds labeled lines such as ``{"Subtotal": "$100.00"}`` and
    ``omit`` drops standard labels, which the extraction eval uses to create
    documents that should be flagged.
    """
    labeled = {
        "Vendor": vendor,
        "Invoice Number": invoice_number,
        "Invoice Date": invoice_date,
        **(extra_lines or {}),
        "Total": total,
    }
    lines = ["OpsPilot fictional demo invoice"] + [
        f"{label}: {value}" for label, value in labeled.items() if label not in omit
    ]
    return render_pdf(lines)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Generate a fictional, text-layer invoice PDF for local demos."
    )
    parser.add_argument("output", type=Path, help="Where to write the PDF")
    parser.add_argument("--invoice-number", default="NW-2026-001")
    parser.add_argument("--vendor", default="Northwind Traders")
    parser.add_argument("--invoice-date", default="2026-09-26")
    parser.add_argument("--total", default="$123.45")
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(
        invoice_pdf(
            invoice_number=args.invoice_number,
            vendor=args.vendor,
            invoice_date=args.invoice_date,
            total=args.total,
        )
    )
