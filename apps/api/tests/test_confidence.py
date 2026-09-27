"""Each confidence signal, weight renormalization, thresholds and rule propagation."""

from datetime import date
from decimal import Decimal

import pytest

from app.confidence import (
    WEIGHTS,
    evaluate,
    format_problem,
    grounding_signal,
    parse_date,
    parse_money,
    score,
    typed_value,
)
from app.llm.provider import ExtractedValue
from app.workflow_config import DocumentTypeSpec, FieldSpec, RuleSpec, default_invoice_config

INVOICE = default_invoice_config().document_types[0]
PAGE = (
    "Vendor: Harbor Supply Co\nInvoice Number: HS-1001\nInvoice Date: 05-Mar-26\n"
    "Subtotal: $100.00\nTax: $10.00\nTotal: $110.00\nCurrency: USD\n"
)


def extracted(name: str, value: str, evidence: str | None = None, page: int = 1) -> ExtractedValue:
    return ExtractedValue(name, value, evidence or f"{name}: {value}", page, None)


def test_weights_sum_to_one_and_score_renormalizes_missing_signals() -> None:
    assert round(sum(WEIGHTS.values()), 6) == 1.0
    assert score({"grounding": 1.0, "format": 1.0}) == 1.0
    assert score({"grounding": 0.0, "format": 1.0}) == round(0.25 / 0.60, 4)
    assert score({"grounding": 1.0, "format": 0.0, "cross_field": 0.0}) == round(0.35 / 0.80, 4)
    assert score({"grounding": None, "format": None}) == 0.0
    assert score({"grounding": 1.0, "self_report": 0.0}) == round(0.35 / 0.40, 4)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2026-03-05", date(2026, 3, 5)),
        ("05-Mar-26", date(2026, 3, 5)),
        ("05-Mar-2026", date(2026, 3, 5)),
        ("05/03/2026", date(2026, 3, 5)),
        ("March 5, 2026", date(2026, 3, 5)),
        ("Mar 5, 2026", date(2026, 3, 5)),
        ("5 March 2026", date(2026, 3, 5)),
        ("2026-02-30", None),
        ("yesterday", None),
    ],
)
def test_date_parsing_accepts_common_layouts(raw: str, expected: date | None) -> None:
    assert parse_date(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("$123.45", Decimal("123.45")),
        ("USD 1,234.50", Decimal("1234.50")),
        ("€99", Decimal("99")),
        ("-12.00", Decimal("-12.00")),
        ("₹1,00,000.00", Decimal("100000.00")),
        ("$11O.OO", None),
        ("12.3.4", None),
        ("", None),
    ],
)
def test_money_parsing_strips_symbols_and_rejects_noise(raw: str, expected: Decimal | None) -> None:
    assert parse_money(raw) == expected


def test_format_problems_are_typed_and_human_readable() -> None:
    date_spec = FieldSpec(name="d", type="date")
    assert format_problem(date_spec, "2026-13-01") == "Value is not a valid date"
    money_spec = FieldSpec(name="m", type="money")
    assert format_problem(money_spec, "ten") == "Value is not a valid amount"
    integer_spec = FieldSpec(name="i", type="integer")
    assert format_problem(integer_spec, "1.5") == "Value is not a whole number"
    assert format_problem(FieldSpec(name="c", type="currency"), "usd") is not None
    assert format_problem(FieldSpec(name="c", type="currency"), "USD") is None
    assert format_problem(FieldSpec(name="n", regex=r"^\d{3}$"), "12") is not None
    assert format_problem(FieldSpec(name="e", enum=["net30", "net60"]), "net90") is not None
    assert format_problem(FieldSpec(name="e", enum=["net30"]), "net30") is None
    assert format_problem(FieldSpec(name="t"), "  ") == "Value is empty"
    assert typed_value(FieldSpec(name="i", type="integer"), "1,200") == Decimal("1200")
    assert typed_value(FieldSpec(name="t"), " text ") == "text"
    assert typed_value(FieldSpec(name="t"), "") is None


def test_grounding_distinguishes_exact_normalized_and_missing_evidence() -> None:
    pages = ["Vendor:   Harbor  Supply\nTotal: $10.00"]
    assert grounding_signal(extracted("total", "$10.00", "Total: $10.00"), pages) == (1.0, [])
    vendor = extracted("vendor", "Harbor Supply", "Vendor: Harbor Supply")
    normalized = grounding_signal(vendor, pages)
    assert normalized[0] == 0.7 and "whitespace" in normalized[1][0]
    missing = grounding_signal(extracted("total", "$99.00", "Total: $99.00"), pages)
    assert missing == (0.0, ["Evidence text not found on page 1"])
    off_page = grounding_signal(extracted("total", "$10.00", "Total: $10.00", page=2), pages)
    assert off_page == (0.0, ["Evidence page 2 does not exist"])
    detached_value = extracted("total", "$10.00", "Amount due today")
    detached = grounding_signal(detached_value, ["Amount due today"])
    assert detached == (0.0, ["Value does not appear in its evidence text"])


def test_clean_invoice_scores_one_and_passes_rules() -> None:
    fields = [
        extracted("vendor", "Harbor Supply Co", "Vendor: Harbor Supply Co"),
        extracted("invoice_number", "HS-1001", "Invoice Number: HS-1001"),
        extracted("invoice_date", "05-Mar-26", "Invoice Date: 05-Mar-26"),
        extracted("subtotal", "$100.00", "Subtotal: $100.00"),
        extracted("tax", "$10.00", "Tax: $10.00"),
        extracted("total", "$110.00", "Total: $110.00"),
        extracted("currency", "USD", "Currency: USD"),
    ]
    evaluation = evaluate(fields, [PAGE], INVOICE)
    by_name = {item.name: item for item in evaluation.fields}
    assert set(by_name) == {name for name in by_name}
    assert all(item.status == "auto" and item.confidence == 1.0 for item in evaluation.fields)
    assert by_name["total"].signals == {
        "grounding": 1.0,
        "format": 1.0,
        "cross_field": 1.0,
        "model_agreement": None,
        "memory_prior": None,
        "self_report": None,
    }
    assert by_name["vendor"].signals["cross_field"] is None
    assert by_name["total"].threshold == 0.9 and by_name["total"].required
    assert [rule.passed for rule in evaluation.rule_results] == [True, None]
    assert evaluation.rule_results[0].message == "Subtotal plus tax must equal total"
    assert evaluation.rule_results[1].expression == "invoice_date <= due_date"


def test_failed_rule_flags_every_referenced_field_with_a_reason() -> None:
    fields = [
        extracted("vendor", "Harbor Supply Co", "Vendor: Harbor Supply Co"),
        extracted("invoice_number", "HS-1001", "Invoice Number: HS-1001"),
        extracted("invoice_date", "05-Mar-26", "Invoice Date: 05-Mar-26"),
        extracted("subtotal", "$100.00", "Subtotal: $100.00"),
        extracted("tax", "$10.00", "Tax: $10.00"),
        extracted("total", "$120.00", "Total: $120.00"),
    ]
    page = PAGE.replace("Total: $110.00", "Total: $120.00")
    evaluation = evaluate(fields, [page], INVOICE)
    by_name = {item.name: item for item in evaluation.fields}
    assert evaluation.rule_results[0].passed is False
    for name in ("subtotal", "tax", "total"):
        assert by_name[name].status == "needs_review"
        assert by_name[name].signals["cross_field"] == 0.0
        reasons = by_name[name].reasons
        assert any(reason.startswith("Rule 'subtotal + tax == total' failed") for reason in reasons)
    # grounding 0.35 + format 0.25 over the applicable weight 0.80 (no self-report).
    assert by_name["total"].confidence == round(0.60 / 0.80, 4)
    assert by_name["vendor"].status == "auto"


def test_format_failure_and_self_report_lower_confidence_below_threshold() -> None:
    fields = [
        extracted("vendor", "Harbor Supply Co", "Vendor: Harbor Supply Co"),
        extracted("invoice_number", "HS-1001", "Invoice Number: HS-1001"),
        ExtractedValue("invoice_date", "2026-13-45", "Invoice Date: 2026-13-45", 1, 0.4),
        extracted("total", "$110.00", "Total: $110.00"),
    ]
    page = PAGE.replace("Invoice Date: 05-Mar-26", "Invoice Date: 2026-13-45")
    evaluation = evaluate(fields, [page], INVOICE)
    by_name = {item.name: item for item in evaluation.fields}
    bad_date = by_name["invoice_date"]
    assert bad_date.status == "needs_review"
    assert bad_date.signals["format"] == 0.0 and bad_date.signals["self_report"] == 0.4
    assert bad_date.confidence == round((0.35 + 0.05 * 0.4) / 0.65, 4)
    assert "Value is not a valid date" in bad_date.reasons
    assert any("below the 0.80 threshold" in reason for reason in bad_date.reasons)


def test_missing_required_fields_are_flagged_and_optional_ones_ignored() -> None:
    fields = [extracted("vendor", "Harbor Supply Co", "Vendor: Harbor Supply Co")]
    evaluation = evaluate(fields, [PAGE], INVOICE)
    by_name = {item.name: item for item in evaluation.fields}
    assert set(by_name) == {"vendor", "invoice_number", "invoice_date", "total"}
    missing = by_name["total"]
    assert missing.status == "needs_review"
    assert missing.value == "" and missing.page_number == 0 and missing.confidence == 0.0
    assert missing.reasons == ["Required field missing"]
    assert all(value is None for value in missing.signals.values())
    assert [rule.passed for rule in evaluation.rule_results] == [None, None]


def test_threshold_is_per_field_and_self_report_is_clamped() -> None:
    strict = DocumentTypeSpec(
        name="receipt",
        fields=[
            FieldSpec(name="merchant", threshold=1.0),
            FieldSpec(name="amount", type="money", threshold=0.5),
        ],
        rules=[RuleSpec(name="positive", expression="amount > 0")],
    )
    fields = [
        ExtractedValue("merchant", "Cafe", "Merchant:  Cafe", 1, 1.7),
        ExtractedValue("amount", "$4.50", "Amount: $4.50", 1, -3.0),
    ]
    evaluation = evaluate(fields, ["Merchant: Cafe\nAmount: $4.50"], strict)
    by_name = {item.name: item for item in evaluation.fields}
    assert by_name["merchant"].signals["self_report"] == 1.0
    assert by_name["merchant"].signals["grounding"] == 0.7
    assert by_name["merchant"].status == "needs_review"
    assert by_name["amount"].signals["self_report"] == 0.0
    assert by_name["amount"].signals["cross_field"] == 1.0
    assert by_name["amount"].status == "auto"


def test_money_and_integer_magnitude_are_bounded_for_storage() -> None:
    money = FieldSpec(name="m", type="money")
    assert format_problem(money, "1" * 30) == "Value is too large to store"
    assert format_problem(money, "999999999999999.9999") is None
    assert format_problem(money, "$1.23456") == "Value has more than 4 decimal places"
    assert format_problem(money, "-1000000000000000") == "Value is too large to store"
    integer = FieldSpec(name="i", type="integer")
    assert format_problem(integer, "1" * 16) == "Value is too large to store"
    assert format_problem(integer, "42") is None
