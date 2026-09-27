"""Deterministic synthetic documents (invoices, purchase orders, delivery notes) with truth.

Every PDF is a one-page text-layer document made of ``Label: value`` lines, the shape the
rules provider and the extraction eval understand. A seeded generator varies label casing
and order, adds noise lines, mixes currencies and date formats, and applies one of a few
perturbations (a missing required field, a mangled amount, an impossible date, totals that
do not add up, a lowercase currency code). The ground truth records the intended values and
which fields a reviewer should be asked to look at.

Names and numbers are fictional. Usage:

    python scripts/generate_synthetic.py --output evals/datasets/generated --count 150
    python scripts/generate_synthetic.py --sample evals/datasets/sample
    python scripts/generate_synthetic.py --examples examples
"""

from __future__ import annotations

import argparse
import json
import random
import re
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

DOCUMENT_TYPES = ("invoice", "purchase_order", "delivery_note")
TEMPLATE_OF = {"invoice": "invoice", "purchase_order": "logistics", "delivery_note": "logistics"}
DEFAULT_SEED = 20260927
DEFAULT_COUNT = 150
SAMPLE_SEED = 12
SAMPLE_COUNT = 12
VARIANTS = (
    "clean",
    "missing_required",
    "mangled_money",
    "invalid_date",
    "totals_mismatch",
    "lowercase_currency",
)
VARIANT_WEIGHTS = (60, 10, 10, 7, 8, 5)
PARTIES = (
    "Harbor Supply Co",
    "Maple Office Products",
    "Blue Ridge Parts",
    "Cedar Freight Lines",
    "Granite Tooling",
    "Sunrise Packaging",
    "Northgate Textiles",
    "Riverbend Chemicals",
)
BUYERS = ("Contoso Logistics", "Northwind Traders", "Fabrikam Depot", "Tailspin Retail")
PEOPLE = ("A. Rivera", "J. Okafor", "M. Lindqvist", "S. Chen", "P. Mehta")
CITIES = ("Rotterdam", "Hamburg", "Pune", "Leeds", "Austin")
CURRENCIES = ("USD", "EUR", "GBP", "INR")
NOISE_LINES = (
    "Thank you for your business",
    "Page 1 of 1",
    "Payment terms: Net 30",
    "Ship via ground freight",
    "Questions? Contact accounts@example.com",
    "Internal batch reference 7",
    "This is a fictional synthetic document",
)
TITLES = {
    "invoice": "Invoice",
    "purchase_order": "Purchase Order",
    "delivery_note": "Delivery Note",
}
REQUIRED = {
    "invoice": ("vendor", "invoice_number", "invoice_date", "total"),
    "purchase_order": ("buyer", "po_number", "order_date", "supplier", "total"),
    "delivery_note": ("supplier", "delivery_note_number", "delivery_date"),
}
LABELS = {
    "vendor": "Vendor",
    "invoice_number": "Invoice Number",
    "invoice_date": "Invoice Date",
    "due_date": "Due Date",
    "subtotal": "Subtotal",
    "tax": "Tax",
    "total": "Total",
    "currency": "Currency",
    "po_number": "PO Number",
    "buyer": "Buyer",
    "order_date": "Order Date",
    "delivery_date": "Delivery Date",
    "supplier": "Supplier",
    "line_count": "Line Count",
    "delivery_note_number": "Delivery Note Number",
    "packages": "Packages",
    "received_by": "Received By",
}
MONEY_FIELDS = ("subtotal", "tax", "total")
DATE_FIELDS = ("invoice_date", "due_date", "order_date", "delivery_date")


@dataclass
class SyntheticCase:
    name: str
    document_type: str
    template: str
    variant: str
    truth: dict[str, str]
    should_flag: list[str] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)

    @property
    def pdf_name(self) -> str:
        return f"{self.name}.pdf"

    def pdf(self) -> bytes:
        return render_pdf(self.lines)

    def manifest_entry(self) -> dict[str, object]:
        entry = asdict(self)
        entry.pop("lines")
        entry["pdf"] = self.pdf_name
        return entry


def render_pdf(lines: list[str]) -> bytes:
    """A one-page Helvetica PDF whose text layer is exactly ``lines``; ASCII only."""
    escaped = [
        line.encode("ascii", "replace")
        .decode("ascii")
        .replace("\\", "\\\\")
        .replace("(", "\\(")
        .replace(")", "\\)")
        for line in lines
    ]
    content = (
        "BT /F1 12 Tf 50 750 Td 16 TL " + " ".join(f"({line}) Tj T*" for line in escaped) + " ET"
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


def format_money(rng: random.Random, amount: Decimal, currency: str) -> str:
    grouped = f"{amount:,.2f}"
    plain = f"{amount:.2f}"
    styles = (
        f"${grouped}" if currency == "USD" else f"{currency} {grouped}",
        f"{currency} {plain}",
        f"{grouped} {currency}",
        plain,
    )
    return rng.choice(styles)


def format_date(rng: random.Random, value: date) -> str:
    pattern = rng.choice(("%Y-%m-%d", "%d-%b-%y", "%b %d, %Y", "%d/%m/%Y", "%d %B %Y"))
    return value.strftime(pattern)


def _amounts(rng: random.Random) -> tuple[Decimal, Decimal, Decimal]:
    subtotal = Decimal(rng.randint(2_000, 950_000)) / 100
    rate = Decimal(rng.choice((0, 5, 8, 18, 20))) / 100
    tax = (subtotal * rate).quantize(Decimal("0.01"))
    return subtotal, tax, subtotal + tax


def _base_values(rng: random.Random, document_type: str, index: int) -> dict[str, str]:
    year = 2026
    issued = date(year, 1, 1) + timedelta(days=rng.randint(0, 300))
    currency = rng.choice(CURRENCIES)
    values: dict[str, str] = {}
    if document_type == "invoice":
        subtotal, tax, total = _amounts(rng)
        values["vendor"] = rng.choice(PARTIES)
        values["invoice_number"] = f"INV-{year}-{index:04d}"
        values["invoice_date"] = format_date(rng, issued)
        if rng.random() < 0.8:
            values["due_date"] = format_date(rng, issued + timedelta(days=rng.choice((14, 30, 45))))
        if rng.random() < 0.75:
            values["subtotal"] = format_money(rng, subtotal, currency)
            values["tax"] = format_money(rng, tax, currency)
        values["total"] = format_money(rng, total, currency)
        if rng.random() < 0.7:
            values["currency"] = currency
        if rng.random() < 0.4:
            values["po_number"] = f"PO-{year}-{rng.randint(1, 999):04d}"
    elif document_type == "purchase_order":
        subtotal, tax, total = _amounts(rng)
        values["buyer"] = rng.choice(BUYERS)
        values["po_number"] = f"PO-{year}-{index:04d}"
        values["order_date"] = format_date(rng, issued)
        if rng.random() < 0.8:
            values["delivery_date"] = format_date(
                rng, issued + timedelta(days=rng.choice((7, 10, 21)))
            )
        values["supplier"] = rng.choice(PARTIES)
        if rng.random() < 0.7:
            values["line_count"] = str(rng.randint(1, 40))
        if rng.random() < 0.75:
            values["subtotal"] = format_money(rng, subtotal, currency)
            values["tax"] = format_money(rng, tax, currency)
        values["total"] = format_money(rng, total, currency)
        if rng.random() < 0.7:
            values["currency"] = currency
    else:
        values["supplier"] = rng.choice(PARTIES)
        values["delivery_note_number"] = f"DN-{year}-{index:04d}"
        if rng.random() < 0.8:
            values["po_number"] = f"PO-{year}-{rng.randint(1, 999):04d}"
        values["delivery_date"] = format_date(rng, issued)
        if rng.random() < 0.7:
            values["packages"] = str(rng.randint(1, 60))
        if rng.random() < 0.6:
            values["received_by"] = rng.choice(PEOPLE)
    return values


def _perturb(
    rng: random.Random, document_type: str, values: dict[str, str], variant: str
) -> tuple[dict[str, str], dict[str, str], list[str]]:
    """Return (truth, printed, should_flag) for the variant; printed may differ from truth."""
    truth = dict(values)
    printed = dict(values)
    if variant == "missing_required":
        name = rng.choice(REQUIRED[document_type])
        printed.pop(name)
        return truth, printed, [name]
    if variant == "mangled_money" and "total" in values:
        # A letter O where a digit should be: the classic OCR-style mistake.
        printed["total"] = re.sub(r"\d", "O", values["total"], count=1)
        return truth, printed, ["total"]
    if variant == "invalid_date":
        candidates = [name for name in DATE_FIELDS if name in values]
        name = rng.choice(candidates)
        printed[name] = rng.choice(("2026-09-31", "31-Sep-26", "2026-02-30"))
        return truth, printed, [name]
    if variant == "totals_mismatch" and "subtotal" in values:
        currency = values.get("currency", "USD")
        subtotal = _parse_amount(values["subtotal"])
        tax = _parse_amount(values["tax"])
        truth["total"] = format_money(rng, subtotal + tax, currency)
        printed["total"] = format_money(rng, subtotal + tax + Decimal("10.00"), currency)
        return truth, printed, ["total"]
    if variant == "lowercase_currency" and "currency" in values:
        printed["currency"] = values["currency"].lower()
        return truth, printed, ["currency"]
    return truth, printed, []


def _parse_amount(text: str) -> Decimal:
    digits = "".join(char for char in text if char.isdigit() or char == ".")
    return Decimal(digits)


def _pick_variant(rng: random.Random, document_type: str, values: dict[str, str]) -> str:
    variant = rng.choices(VARIANTS, weights=VARIANT_WEIGHTS, k=1)[0]
    if variant == "mangled_money" and "total" not in values:
        return "clean"
    if variant == "totals_mismatch" and "subtotal" not in values:
        return "clean"
    if variant == "lowercase_currency" and "currency" not in values:
        return "clean"
    return variant


def _style_label(rng: random.Random, label: str) -> str:
    return rng.choice((label, label, label.upper(), label.lower()))


def build_case(
    rng: random.Random, index: int, document_type: str, variant: str | None = None
) -> SyntheticCase:
    values = _base_values(rng, document_type, index)
    chosen = variant or _pick_variant(rng, document_type, values)
    truth, printed, should_flag = _perturb(rng, document_type, values, chosen)
    if chosen != "clean" and not should_flag:
        chosen = "clean"
    title = TITLES[document_type]
    heading = rng.choice((title, title.upper(), f"{title} - {rng.choice(CITIES)} office"))
    body = [f"{_style_label(rng, LABELS[name])}: {value}" for name, value in printed.items()]
    if rng.random() < 0.5:
        rng.shuffle(body)
    if document_type == "delivery_note" and rng.random() < 0.6:
        body.insert(0, f"Dispatched from {rng.choice(CITIES)} depot")
    for _ in range(rng.randint(0, 3)):
        body.insert(rng.randint(0, len(body)), rng.choice(NOISE_LINES))
    name = f"{document_type.replace('_', '-')}-{index:04d}-{chosen.replace('_', '-')}"
    return SyntheticCase(
        name=name,
        document_type=document_type,
        template=TEMPLATE_OF[document_type],
        variant=chosen,
        truth=truth,
        should_flag=should_flag,
        lines=[heading, *body],
    )


def generate_dataset(count: int = DEFAULT_COUNT, seed: int = DEFAULT_SEED) -> list[SyntheticCase]:
    """``count`` cases cycling through the document types; identical for the same seed."""
    rng = random.Random(seed)
    return [
        build_case(rng, index, DOCUMENT_TYPES[(index - 1) % len(DOCUMENT_TYPES)])
        for index in range(1, count + 1)
    ]


def sample_cases() -> list[SyntheticCase]:
    """Twelve committed cases: for each type two clean and two perturbed documents."""
    rng = random.Random(SAMPLE_SEED)
    plan = {
        "invoice": ("clean", "clean", "mangled_money", "missing_required"),
        "purchase_order": ("clean", "clean", "totals_mismatch", "invalid_date"),
        "delivery_note": ("clean", "clean", "missing_required", "invalid_date"),
    }
    cases = []
    index = 0
    for document_type, variants in plan.items():
        for variant in variants:
            index += 1
            cases.append(_forced_case(rng, index, document_type, variant))
    return cases


def _forced_case(rng: random.Random, index: int, document_type: str, variant: str) -> SyntheticCase:
    # Draw until the variant is applicable (a mangled total needs a total line, and so on).
    for _ in range(50):
        case = build_case(rng, index, document_type, variant)
        if case.variant == variant:
            return case
    raise RuntimeError(f"Could not build a {variant} {document_type}")


def example_cases() -> dict[str, SyntheticCase]:
    """Clean Contoso documents committed under examples/ for demos and tests."""
    rng = random.Random(7)
    return {
        "contoso-purchase-order.pdf": _forced_case(rng, 42, "purchase_order", "clean"),
        "contoso-delivery-note.pdf": _forced_case(rng, 42, "delivery_note", "clean"),
    }


def write_dataset(cases: list[SyntheticCase], directory: Path, seed: int) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    for stale in directory.glob("*.pdf"):
        stale.unlink()
    for case in cases:
        (directory / case.pdf_name).write_bytes(case.pdf())
    manifest = {
        "generator": "scripts/generate_synthetic.py",
        "seed": seed,
        "count": len(cases),
        "cases": [case.manifest_entry() for case in cases],
    }
    path = directory / "manifest.json"
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--output", type=Path, help="Write the generated dataset here")
    parser.add_argument("--count", type=int, default=DEFAULT_COUNT)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--sample", type=Path, help="Write the 12-document committed sample")
    parser.add_argument("--examples", type=Path, help="Write the Contoso example PDFs")
    args = parser.parse_args()
    if not (args.output or args.sample or args.examples):
        parser.error("Choose --output, --sample or --examples")
    if args.output:
        path = write_dataset(generate_dataset(args.count, args.seed), args.output, args.seed)
        print(f"Wrote {args.count} documents and {path}")
    if args.sample:
        path = write_dataset(sample_cases(), args.sample, SAMPLE_SEED)
        print(f"Wrote the {SAMPLE_COUNT}-document sample and {path}")
    if args.examples:
        args.examples.mkdir(parents=True, exist_ok=True)
        for filename, case in example_cases().items():
            (args.examples / filename).write_bytes(case.pdf())
            print(f"Wrote {args.examples / filename}: {json.dumps(case.truth)}")


if __name__ == "__main__":
    main()
