"""Versioned per-organization workflow configuration: document types, fields and rules."""

from __future__ import annotations

import json
import re
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from app import rules

FieldType = Literal["text", "identifier", "date", "money", "integer", "currency"]
ReviewPolicy = Literal["always", "threshold"]
ActionPolicy = Literal["auto", "needs_approval", "forbidden"]
FIELD_NAME_PATTERN = r"^[a-z][a-z0-9_]{0,99}$"
DOCUMENT_TYPE_PATTERN = r"^[a-z][a-z0-9_]{0,49}$"
MAX_REGEX_LENGTH = 200
_BRACE_QUANTIFIER = re.compile(r"\{\d*,?\d*\}")


def default_label(name: str) -> str:
    return name.replace("_", " ").title()


def has_nested_quantifier(pattern: str) -> bool:
    """Detect a quantifier applied to a group that itself repeats or alternates.

    Patterns such as ``(a+)+``, ``(\\d*)*`` and ``(a|aa)+`` backtrack exponentially
    on non-matching input. Tenant regexes run on every extracted value, so they
    are rejected at configuration time. Character classes and escapes are skipped.
    """
    stack: list[bool] = []  # per open group: contains a quantifier or alternation
    index = 0
    length = len(pattern)
    while index < length:
        char = pattern[index]
        if char == "\\":
            index += 2
            continue
        if char == "[":
            end = index + 1
            if end < length and pattern[end] == "^":
                end += 1
            if end < length and pattern[end] == "]":
                end += 1
            while end < length and pattern[end] != "]":
                end += 2 if pattern[end] == "\\" else 1
            index = end + 1
            continue
        if char == "(":
            stack.append(False)
            index += 1
            if index < length and pattern[index] == "?":
                # Skip the extension marker: (?:  (?=  (?!  (?<=  (?<!  (?P<name>  (?P=name)
                index += 1
                while index < length and pattern[index] not in ":=!)>":
                    index += 1
                index += 1
            continue
        if char == ")":
            inner = stack.pop() if stack else False
            index += 1
            quantified = index < length and (
                pattern[index] in "+*?" or _BRACE_QUANTIFIER.match(pattern, index) is not None
            )
            if quantified and inner:
                return True
            if stack:
                stack[-1] = stack[-1] or inner or quantified
            continue
        if char in "+*?|" or (char == "{" and _BRACE_QUANTIFIER.match(pattern, index)):
            if stack:
                stack[-1] = True
        index += 1
    return False


class FieldSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=FIELD_NAME_PATTERN)
    label: str = Field(default="", max_length=100)
    type: FieldType = "text"
    required: bool = False
    regex: str | None = Field(default=None, max_length=500)
    enum: list[str] | None = Field(default=None, max_length=500)
    threshold: float = Field(default=0.8, ge=0, le=1)

    @field_validator("regex")
    @classmethod
    def compile_regex(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if len(value) > MAX_REGEX_LENGTH:
            raise ValueError(f"Regular expression is longer than {MAX_REGEX_LENGTH} characters")
        try:
            re.compile(value)
        except re.error as exc:
            raise ValueError(f"Invalid regular expression: {exc}") from exc
        if has_nested_quantifier(value):
            raise ValueError(
                "Regular expression repeats a group that itself repeats or alternates"
            )
        return value

    @model_validator(mode="after")
    def fill_label(self) -> FieldSpec:
        if not self.label.strip():
            self.label = default_label(self.name)
        return self


class RuleSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    expression: str = Field(min_length=1, max_length=500)
    tolerance: Decimal = Field(default=Decimal("0.01"), ge=0)
    message: str | None = Field(default=None, max_length=300)

    @field_validator("expression")
    @classmethod
    def parse_expression(cls, value: str) -> str:
        # Raises ValueError for anything outside the rule grammar.
        rules.parse(value)
        return value.strip()

    def parsed(self) -> rules.Comparison:
        return rules.parse(self.expression)


class DocumentTypeSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=DOCUMENT_TYPE_PATTERN)
    label: str = Field(default="", max_length=100)
    detect: list[str] = Field(default_factory=list, max_length=50)
    fields: list[FieldSpec] = Field(min_length=1, max_length=100)
    rules: list[RuleSpec] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def check_references(self) -> DocumentTypeSpec:
        if not self.label.strip():
            self.label = default_label(self.name)
        names = [field.name for field in self.fields]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            raise ValueError(f"Duplicate field names: {', '.join(duplicates)}")
        known = set(names)
        rule_names = [rule.name for rule in self.rules]
        repeated = sorted({name for name in rule_names if rule_names.count(name) > 1})
        if repeated:
            raise ValueError(f"Duplicate rule names: {', '.join(repeated)}")
        for rule in self.rules:
            unknown = sorted(rules.identifiers(rule.parsed()) - known)
            if unknown:
                raise ValueError(f"Rule '{rule.name}' references unknown field: {unknown[0]}")
        return self

    def field(self, name: str) -> FieldSpec | None:
        return next((field for field in self.fields if field.name == name), None)


class WorkflowConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_types: list[DocumentTypeSpec] = Field(min_length=1, max_length=50)
    review_policy: ReviewPolicy = "always"
    review_sla_minutes: int = Field(default=240, ge=1, le=60 * 24 * 30)
    baseline_minutes: int = Field(default=12, ge=0, le=60 * 24)
    action_policies: dict[str, ActionPolicy] = Field(default_factory=dict)

    @model_validator(mode="after")
    def unique_document_types(self) -> WorkflowConfigModel:
        names = [item.name for item in self.document_types]
        if len(set(names)) != len(names):
            raise ValueError("Document type names must be unique")
        return self

    def document_type(self, name: str) -> DocumentTypeSpec | None:
        return next((item for item in self.document_types if item.name == name), None)


def default_invoice_config() -> WorkflowConfigModel:
    return WorkflowConfigModel(
        document_types=[
            DocumentTypeSpec(
                name="invoice",
                label="Invoice",
                detect=["invoice"],
                fields=[
                    FieldSpec(name="vendor", type="text", required=True, threshold=0.8),
                    FieldSpec(
                        name="invoice_number",
                        type="identifier",
                        required=True,
                        regex=r"^[A-Za-z0-9-/]{3,40}$",
                        threshold=0.8,
                    ),
                    FieldSpec(name="invoice_date", type="date", required=True, threshold=0.8),
                    FieldSpec(name="due_date", type="date"),
                    FieldSpec(name="subtotal", type="money"),
                    FieldSpec(name="tax", type="money"),
                    FieldSpec(name="total", type="money", required=True, threshold=0.9),
                    FieldSpec(name="currency", type="currency", regex=r"^[A-Z]{3}$"),
                    FieldSpec(name="po_number", label="PO Number", type="identifier"),
                ],
                rules=[
                    RuleSpec(
                        name="totals_add_up",
                        expression="subtotal + tax == total",
                        tolerance=Decimal("0.01"),
                        message="Subtotal plus tax must equal total",
                    ),
                    RuleSpec(
                        name="due_after_issue",
                        expression="invoice_date <= due_date",
                        message="Due date must not precede the invoice date",
                    ),
                ],
            )
        ]
    )


class InvalidWorkflowConfig(ValueError):
    pass


def load_config(config_json: str) -> WorkflowConfigModel:
    """Parse a stored configuration, upgrading the Phase 1 shape to the full model.

    Rows written before Phase 2 stored ``{"document_types": ["invoice"], "fields": []}``.
    Those organizations keep the default invoice workflow.
    """
    try:
        raw = json.loads(config_json or "{}")
    except ValueError as exc:
        raise InvalidWorkflowConfig("Workflow configuration is not valid JSON") from exc
    if not isinstance(raw, dict):
        raise InvalidWorkflowConfig("Workflow configuration must be a JSON object")
    types = raw.get("document_types")
    legacy = not isinstance(types, list) or not types or all(isinstance(t, str) for t in types)
    if legacy:
        return default_invoice_config()
    try:
        return WorkflowConfigModel.model_validate(raw)
    except ValidationError as exc:
        raise InvalidWorkflowConfig(f"Workflow configuration is invalid: {exc}") from exc
