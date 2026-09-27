"""The rule grammar must be small, predictable and never reach eval()."""

from datetime import date
from decimal import Decimal

import pytest

from app import rules

Values = dict[str, rules.Value]


def check(expression: str, values: Values, tolerance: str = "0.01") -> bool | None:
    return rules.evaluate(rules.parse(expression), values, Decimal(tolerance))


def test_parses_arithmetic_with_precedence_and_parentheses() -> None:
    assert check("1 + 2 * 3 == 7", {}) is True
    assert check("(1 + 2) * 3 == 9", {}) is True
    assert check("10 - 4 - 3 == 3", {}) is True
    assert check("12 / 4 / 3 == 1", {}) is True
    two: Values = {"a": Decimal("2")}
    assert check("-a + 5 == 3", two) is True
    assert check("--a == 2", two) is True


def test_identifiers_are_collected_from_both_sides() -> None:
    tree = rules.parse("subtotal + tax == total")
    assert rules.identifiers(tree) == {"subtotal", "tax", "total"}


def test_equality_uses_tolerance_and_ordering_is_exact() -> None:
    values: Values = {
        "subtotal": Decimal("100.00"),
        "tax": Decimal("10.00"),
        "total": Decimal("110.004"),
    }
    assert check("subtotal + tax == total", values) is True
    assert check("subtotal + tax != total", values) is False
    assert check("subtotal + tax == total", values, tolerance="0.001") is False
    assert check("subtotal < total", values) is True
    assert check("total <= subtotal", values) is False
    assert check("total > subtotal", values) is True
    assert check("subtotal >= subtotal", values) is True


def test_dates_compare_directly_and_strings_only_support_equality() -> None:
    values: Values = {
        "invoice_date": date(2026, 9, 5),
        "due_date": date(2026, 10, 5),
        "vendor": "Harbor",
        "other": "Harbor",
    }
    assert check("invoice_date <= due_date", values) is True
    assert check("invoice_date > due_date", values) is False
    assert check("invoice_date == due_date", values) is False
    assert check("vendor == other", values) is True
    assert check("vendor != other", values) is False
    assert check("vendor < other", values) is None


def test_missing_or_mismatched_operands_are_not_evaluable() -> None:
    cases: list[tuple[str, Values]] = [
        ("subtotal + tax == total", {"subtotal": Decimal("1")}),
        ("a == b", {"a": Decimal("1"), "b": date(2026, 1, 1)}),
        ("a / b == 1", {"a": Decimal("1"), "b": Decimal("0")}),
        ("a + 1 == 2", {"a": "text"}),
        ("unknown == 1", {}),
        ("a == 1", {"a": None}),
    ]
    for expression, values in cases:
        assert check(expression, values) is None, expression


@pytest.mark.parametrize(
    "expression",
    [
        "",
        "   ",
        "subtotal + tax",
        "total",
        "abs(total) == 1",
        "total.real == 1",
        "__import__ == 1",
        "_private == 1",
        "a == b == c",
        "a === b",
        "a == 'text'",
        "a == 1;",
        "(a == 1",
        "a ** 2 == 4",
        "a == 1e5",
        "a[0] == 1",
        "lambda: 1 == 1",
    ],
)
def test_rejects_unsupported_syntax(expression: str) -> None:
    with pytest.raises(ValueError):
        rules.parse(expression)


def test_parser_reports_position_of_problem() -> None:
    with pytest.raises(ValueError, match="Function calls are not supported"):
        rules.parse("round(total) == 1")
    with pytest.raises(ValueError, match="Unexpected character '\\.'"):
        rules.parse("a.b == 1")
