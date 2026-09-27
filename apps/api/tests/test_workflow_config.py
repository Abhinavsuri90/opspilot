"""Workflow configuration validation and the upgrade path for Phase 1 rows."""

import json
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.workflow_config import (
    DocumentTypeSpec,
    FieldSpec,
    InvalidWorkflowConfig,
    RuleSpec,
    WorkflowConfigModel,
    default_invoice_config,
    load_config,
)


def test_default_invoice_config_matches_the_phase_2_contract() -> None:
    config = default_invoice_config()
    assert config.review_policy == "always"
    assert config.review_sla_minutes == 240
    assert config.baseline_minutes == 12
    invoice = config.document_types[0]
    assert invoice.name == "invoice" and invoice.label == "Invoice"
    fields = {field.name: field for field in invoice.fields}
    assert set(fields) == {
        "vendor",
        "invoice_number",
        "invoice_date",
        "due_date",
        "subtotal",
        "tax",
        "total",
        "currency",
        "po_number",
    }
    assert fields["total"].required and fields["total"].threshold == 0.9
    assert fields["invoice_number"].regex == r"^[A-Za-z0-9-/]{3,40}$"
    assert fields["po_number"].label == "PO Number"
    assert fields["due_date"].label == "Due Date"
    assert [rule.expression for rule in invoice.rules] == [
        "subtotal + tax == total",
        "invoice_date <= due_date",
    ]
    assert invoice.rules[0].tolerance == Decimal("0.01")


def test_round_trips_through_json() -> None:
    config = default_invoice_config()
    assert load_config(config.model_dump_json()) == config


@pytest.mark.parametrize(
    "stored",
    [
        '{"document_types": ["invoice"], "fields": []}',
        '{"document_types": ["custom"], "fields": []}',
        "{}",
        "",
    ],
)
def test_legacy_rows_upgrade_to_the_default_invoice_config(stored: str) -> None:
    assert load_config(stored) == default_invoice_config()


def test_invalid_stored_config_is_reported() -> None:
    with pytest.raises(InvalidWorkflowConfig):
        load_config("not json")
    with pytest.raises(InvalidWorkflowConfig):
        load_config(json.dumps({"document_types": [{"name": "invoice"}]}))
    with pytest.raises(InvalidWorkflowConfig):
        load_config("[]")


def test_field_labels_default_from_names_and_regex_must_compile() -> None:
    assert FieldSpec(name="invoice_number").label == "Invoice Number"
    assert FieldSpec(name="vendor", label=" Supplier ").label == " Supplier "
    with pytest.raises(ValidationError, match="Invalid regular expression"):
        FieldSpec(name="vendor", regex="(")
    with pytest.raises(ValidationError):
        FieldSpec(name="Vendor Name")
    with pytest.raises(ValidationError):
        FieldSpec(name="vendor", threshold=1.5)
    with pytest.raises(ValidationError):
        FieldSpec(name="vendor", unexpected=True)  # type: ignore[call-arg]


def test_rules_are_validated_against_the_field_list() -> None:
    with pytest.raises(ValidationError, match="Function calls"):
        RuleSpec(name="bad", expression="abs(total) == 1")
    with pytest.raises(ValidationError, match="unknown field: subtotal"):
        DocumentTypeSpec(
            name="invoice",
            fields=[FieldSpec(name="total")],
            rules=[RuleSpec(name="sum", expression="subtotal + tax == total")],
        )
    with pytest.raises(ValidationError, match="Duplicate field names: total"):
        DocumentTypeSpec(name="invoice", fields=[FieldSpec(name="total"), FieldSpec(name="total")])
    with pytest.raises(ValidationError, match="Duplicate rule names: sum"):
        DocumentTypeSpec(
            name="invoice",
            fields=[FieldSpec(name="total"), FieldSpec(name="tax")],
            rules=[
                RuleSpec(name="sum", expression="tax <= total"),
                RuleSpec(name="sum", expression="tax < total"),
            ],
        )
    with pytest.raises(ValidationError):
        DocumentTypeSpec(name="invoice", fields=[])


def test_workflow_config_requires_unique_document_types() -> None:
    invoice = default_invoice_config().document_types[0]
    with pytest.raises(ValidationError, match="unique"):
        WorkflowConfigModel(document_types=[invoice, invoice])
    with pytest.raises(ValidationError):
        WorkflowConfigModel(document_types=[])
    with pytest.raises(ValidationError):
        WorkflowConfigModel.model_validate(
            {"document_types": [invoice.model_dump()], "review_policy": "sometimes"}
        )
    with pytest.raises(ValidationError):
        WorkflowConfigModel.model_validate(
            {"document_types": [invoice.model_dump()], "action_policies": {"sheet": "maybe"}}
        )
    config = WorkflowConfigModel(
        document_types=[invoice],
        review_policy="threshold",
        action_policies={"append_sheet_row": "needs_approval"},
    )
    assert config.document_type("invoice") is invoice
    assert config.document_type("receipt") is None


@pytest.mark.parametrize(
    "pattern",
    ["(a+)+", r"(\d*)*", "(a|aa)+", "((ab)*)+", "(?:x+)*", "(a?){2,}", r"^(\w+\s?)*$"],
)
def test_rejects_regexes_that_repeat_a_repeating_group(pattern: str) -> None:
    with pytest.raises(ValidationError, match="repeats a group"):
        FieldSpec(name="x", regex=pattern)


@pytest.mark.parametrize(
    "pattern",
    [
        r"^[A-Za-z0-9-/]{3,40}$",
        "(?:ab)+",
        r"^(\d{3})-(\d{4})$",
        "net(30|60)",
        r"[+*?]+",
        r"\(a+\)+",
        "(a)(b)+",
        r"(?P<code>[A-Z]{2})-\d+",
    ],
)
def test_accepts_linear_regexes(pattern: str) -> None:
    assert FieldSpec(name="x", regex=pattern).regex == pattern


def test_regex_length_is_capped() -> None:
    with pytest.raises(ValidationError, match="longer than 200"):
        FieldSpec(name="x", regex="a" * 201)
    assert FieldSpec(name="x", regex="a" * 200).regex == "a" * 200
