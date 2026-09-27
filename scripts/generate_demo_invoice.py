"""Generate a small, text-layer PDF containing fictional invoice data."""

import argparse
from pathlib import Path


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
    escaped = [
        line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        for line in lines
    ]
    content = (
        "BT /F1 12 Tf 50 750 Td 18 TL "
        + " ".join(f"({line}) Tj T*" for line in escaped)
        + " ET"
    )
    stream = content.encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>"
        ),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream",
    ]
    data = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, body in enumerate(objects, start=1):
        offsets.append(len(data))
        data.extend(f"{number} 0 obj\n".encode() + body + b"\nendobj\n")
    xref_at = len(data)
    data.extend(f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        data.extend(f"{offset:010d} 00000 n \n".encode())
    data.extend(
        f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref_at}\n%%EOF\n".encode()
    )
    return bytes(data)


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
