"""Multi-signal field confidence. Weights and rationale: docs/adr/006-confidence-scoring.md."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Literal

from app import rules
from app.llm.provider import ExtractedValue
from app.workflow_config import DocumentTypeSpec, FieldSpec, RuleSpec

WEIGHTS: dict[str, float] = {
    "grounding": 0.35,
    "format": 0.25,
    "cross_field": 0.20,
    "model_agreement": 0.10,
    "memory_prior": 0.05,
    "self_report": 0.05,
}
DATE_FORMATS = (
    "%Y-%m-%d",
    "%d-%b-%y",
    "%d-%b-%Y",
    "%d/%m/%Y",
    "%d.%m.%Y",
    "%B %d, %Y",
    "%b %d, %Y",
    "%d %B %Y",
    "%d %b %Y",
    "%Y/%m/%d",
)
_MONEY_NOISE = re.compile(r"[A-Za-z$€£¥₹\s,]")
# Stored as NUMERIC(20, 4); keep a margin below 10**16 so quantizing cannot overflow.
MAX_AMOUNT_MAGNITUDE = Decimal(10) ** 15
MAX_DECIMAL_PLACES = 4
_WHITESPACE = re.compile(r"\s+")
FieldStatus = Literal["auto", "needs_review"]


@dataclass
class FieldAssessment:
    name: str
    value: str
    evidence: str
    page_number: int
    field_type: str
    required: bool
    threshold: float
    confidence: float
    signals: dict[str, float | None]
    reasons: list[str]
    status: FieldStatus


@dataclass(frozen=True)
class RuleResult:
    name: str
    expression: str
    passed: bool | None
    message: str


@dataclass
class Evaluation:
    fields: list[FieldAssessment]
    rule_results: list[RuleResult] = field(default_factory=list)


def parse_date(value: str) -> date | None:
    text = value.strip()
    for pattern in DATE_FORMATS:
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            continue
    return None


def parse_money(value: str) -> Decimal | None:
    cleaned = _MONEY_NOISE.sub("", value)
    if not re.fullmatch(r"-?\d+(?:\.\d+)?", cleaned):
        return None
    try:
        amount = Decimal(cleaned)
    except InvalidOperation:
        return None
    return amount if amount.is_finite() else None


def parse_integer(value: str) -> Decimal | None:
    cleaned = value.strip().replace(",", "")
    return Decimal(cleaned) if re.fullmatch(r"-?\d+", cleaned) else None


def typed_value(spec: FieldSpec, value: str) -> rules.Value:
    """Convert a raw string to the type rules compare on; None when it does not parse."""
    if not value.strip():
        return None
    if spec.type == "date":
        return parse_date(value)
    if spec.type == "money":
        return parse_money(value)
    if spec.type == "integer":
        return parse_integer(value)
    return value.strip()


def magnitude_problem(amount: Decimal) -> str | None:
    """Reject numbers the database column or a downstream ledger could not hold."""
    if abs(amount) >= MAX_AMOUNT_MAGNITUDE:
        return "Value is too large to store"
    exponent = amount.as_tuple().exponent
    if isinstance(exponent, int) and exponent < -MAX_DECIMAL_PLACES:
        return f"Value has more than {MAX_DECIMAL_PLACES} decimal places"
    return None


def format_problem(spec: FieldSpec, value: str) -> str | None:
    """Return a human readable reason when the value fails the field's format checks."""
    text = value.strip()
    if not text:
        return "Value is empty"
    if spec.type == "date" and parse_date(text) is None:
        return "Value is not a valid date"
    if spec.type == "money":
        amount = parse_money(text)
        if amount is None:
            return "Value is not a valid amount"
        if (problem := magnitude_problem(amount)) is not None:
            return problem
    if spec.type == "integer":
        number = parse_integer(text)
        if number is None:
            return "Value is not a whole number"
        if (problem := magnitude_problem(number)) is not None:
            return problem
    if spec.type == "currency" and not re.fullmatch(r"[A-Z]{3}", text):
        return "Value is not a three-letter ISO currency code"
    if spec.regex is not None and re.fullmatch(spec.regex, text) is None:
        return f"Value does not match the expected pattern for {spec.label}"
    if spec.enum is not None and text not in spec.enum:
        return f"Value is not one of the allowed options for {spec.label}"
    return None


def _normalize(text: str) -> str:
    return _WHITESPACE.sub(" ", text).strip()


def grounding_signal(value: ExtractedValue, pages: list[str]) -> tuple[float, list[str]]:
    if not 1 <= value.page_number <= len(pages):
        return 0.0, [f"Evidence page {value.page_number} does not exist"]
    page = pages[value.page_number - 1]
    if _normalize(value.value) not in _normalize(value.evidence):
        return 0.0, ["Value does not appear in its evidence text"]
    if value.evidence in page:
        return 1.0, []
    if _normalize(value.evidence) in _normalize(page):
        return 0.7, [f"Evidence only matches page {value.page_number} after whitespace changes"]
    return 0.0, [f"Evidence text not found on page {value.page_number}"]


def evaluate_rules(values: dict[str, rules.Value], type_spec: DocumentTypeSpec) -> list[RuleResult]:
    results = []
    for rule in type_spec.rules:
        passed = rules.evaluate(rule.parsed(), values, rule.tolerance)
        results.append(
            RuleResult(rule.name, rule.expression, passed, rule.message or rule.expression)
        )
    return results


def _rule_reason(rule: RuleSpec) -> str:
    reason = f"Rule '{rule.expression}' failed"
    return f"{reason} ({rule.message})" if rule.message else reason


def score(signals: dict[str, float | None]) -> float:
    """Weighted mean over the signals that apply; weights renormalize when some are None."""
    total_weight = sum(WEIGHTS[name] for name, value in signals.items() if value is not None)
    if total_weight == 0:
        return 0.0
    weighted = sum(WEIGHTS[name] * value for name, value in signals.items() if value is not None)
    return round(weighted / total_weight, 4)


def evaluate(
    fields: list[ExtractedValue], pages: list[str], type_spec: DocumentTypeSpec
) -> Evaluation:
    by_name = {value.name: value for value in fields}
    typed: dict[str, rules.Value] = {}
    for spec in type_spec.fields:
        extracted = by_name.get(spec.name)
        typed[spec.name] = typed_value(spec, extracted.value) if extracted else None
    rule_results = evaluate_rules(typed, type_spec)
    rule_outcomes = {
        rule.name: (rule, result.passed)
        for rule, result in zip(type_spec.rules, rule_results, strict=True)
    }

    assessments: list[FieldAssessment] = []
    for spec in type_spec.fields:
        extracted = by_name.get(spec.name)
        if extracted is None:
            if spec.required:
                assessments.append(_missing(spec))
            continue
        signals: dict[str, float | None] = dict.fromkeys(WEIGHTS)
        reasons: list[str] = []
        signals["grounding"], grounding_reasons = grounding_signal(extracted, pages)
        reasons.extend(grounding_reasons)
        problem = format_problem(spec, extracted.value)
        signals["format"] = 0.0 if problem else 1.0
        if problem:
            reasons.append(problem)
        relevant = [
            (rule, passed)
            for rule, passed in rule_outcomes.values()
            if spec.name in rules.identifiers(rule.parsed()) and passed is not None
        ]
        if relevant:
            failed = [rule for rule, passed in relevant if passed is False]
            signals["cross_field"] = 0.0 if failed else 1.0
            reasons.extend(_rule_reason(rule) for rule in failed)
        if extracted.self_confidence is not None:
            signals["self_report"] = min(1.0, max(0.0, float(extracted.self_confidence)))
        confidence = score(signals)
        status: FieldStatus = "auto" if confidence >= spec.threshold else "needs_review"
        if status == "needs_review":
            reasons.append(
                f"Confidence {confidence:.2f} is below the {spec.threshold:.2f} threshold"
            )
        assessments.append(
            FieldAssessment(
                name=spec.name,
                value=extracted.value,
                evidence=extracted.evidence,
                page_number=extracted.page_number,
                field_type=spec.type,
                required=spec.required,
                threshold=spec.threshold,
                confidence=confidence,
                signals=signals,
                reasons=reasons,
                status=status,
            )
        )
    return Evaluation(fields=assessments, rule_results=rule_results)


def _missing(spec: FieldSpec) -> FieldAssessment:
    return FieldAssessment(
        name=spec.name,
        value="",
        evidence="",
        page_number=0,
        field_type=spec.type,
        required=True,
        threshold=spec.threshold,
        confidence=0.0,
        signals=dict.fromkeys(WEIGHTS),
        reasons=["Required field missing"],
        status="needs_review",
    )
