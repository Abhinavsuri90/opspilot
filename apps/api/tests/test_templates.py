"""Logistics template, document-type detection and extraction of purchase orders and notes."""

import random
from pathlib import Path

import pytest
from scripts.generate_synthetic import DOCUMENT_TYPES, build_case, example_cases, render_pdf

from app.confidence import evaluate
from app.llm.provider import MockInvoiceProvider, detect_document_type, detection_score, pdf_pages
from app.workflow_config import (
    DocumentTypeSpec,
    FieldSpec,
    WorkflowConfigModel,
    default_invoice_config,
    default_logistics_config,
    template_config,
)

EXAMPLES = Path(__file__).parents[3] / "examples"
LOGISTICS = default_logistics_config()


def _name(spec: FieldSpec | None) -> str | None:
    return spec.name if spec is not None else None


def test_default_logistics_config_contract() -> None:
    assert [item.name for item in LOGISTICS.document_types] == ["purchase_order", "delivery_note"]
    order, note = LOGISTICS.document_types
    assert order.label == "Purchase Order"
    assert order.detect == ["purchase order", "po number"]
    fields = {field.name: field for field in order.fields}
    assert list(fields) == [
        "buyer",
        "po_number",
        "order_date",
        "delivery_date",
        "supplier",
        "line_count",
        "subtotal",
        "tax",
        "total",
        "currency",
    ]
    assert {name for name, field in fields.items() if field.required} == {
        "buyer",
        "po_number",
        "order_date",
        "supplier",
        "total",
    }
    assert fields["po_number"].type == "identifier" and fields["po_number"].label == "PO Number"
    assert fields["line_count"].type == "integer"
    assert fields["total"].type == "money" and fields["total"].threshold == 0.9
    assert [rule.expression for rule in order.rules] == [
        "subtotal + tax == total",
        "order_date <= delivery_date",
    ]
    assert note.label == "Delivery Note" and note.detect == ["delivery note", "dispatch"]
    note_fields = {field.name: field for field in note.fields}
    assert list(note_fields) == [
        "supplier",
        "delivery_note_number",
        "po_number",
        "delivery_date",
        "packages",
        "received_by",
    ]
    assert {name for name, field in note_fields.items() if field.required} == {
        "supplier",
        "delivery_note_number",
        "delivery_date",
    }
    assert note_fields["packages"].type == "integer" and note.rules == []
    assert LOGISTICS.review_policy == "always"
    assert WorkflowConfigModel.model_validate_json(LOGISTICS.model_dump_json()) == LOGISTICS


def test_template_lookup_and_identity_helpers() -> None:
    assert template_config("invoice") == default_invoice_config()
    assert template_config("logistics") == LOGISTICS
    with pytest.raises(ValueError, match="Unknown workflow template"):
        template_config("receipts")
    invoice = default_invoice_config().document_types[0]
    order, note = LOGISTICS.document_types
    assert _name(invoice.primary_identifier()) == "invoice_number"
    assert _name(invoice.party_field()) == "vendor"
    assert _name(order.primary_identifier()) == "po_number"
    assert _name(order.party_field()) == "supplier"
    assert _name(note.primary_identifier()) == "delivery_note_number"
    assert _name(note.party_field()) == "supplier"
    bare = DocumentTypeSpec(name="memo", fields=[FieldSpec(name="title")])
    assert bare.primary_identifier() is None and bare.party_field() is None
    optional_only = DocumentTypeSpec(
        name="ticket",
        fields=[FieldSpec(name="ref", type="identifier"), FieldSpec(name="supplier")],
    )
    assert _name(optional_only.primary_identifier()) == "ref"


def test_detection_counts_keywords_and_favours_the_heading() -> None:
    note = pdf_pages(
        render_pdf(
            [
                "Delivery Note",
                "Supplier: Cedar Freight Lines",
                "Delivery Note Number: DN-1",
                "PO Number: PO-77",
                "Delivery Date: 2026-03-01",
            ]
        )
    )
    assert detect_document_type(note, LOGISTICS).name == "delivery_note"
    order = pdf_pages(
        render_pdf(
            [
                "PURCHASE ORDER",
                "Buyer: Contoso Logistics",
                "PO Number: PO-77",
                "Supplier: Cedar Freight Lines",
                "Order Date: 2026-03-01",
                "Total: $10.00",
            ]
        )
    )
    assert detect_document_type(order, LOGISTICS).name == "purchase_order"
    # A single body mention of each keyword: the title decides.
    tie = pdf_pages(render_pdf(["Delivery note", "PO Number: PO-77"]))
    assert detection_score(tie, LOGISTICS.document_types[0]) == 1
    assert detection_score(tie, LOGISTICS.document_types[1]) == 3
    assert detect_document_type(tie, LOGISTICS).name == "delivery_note"
    nothing = pdf_pages(render_pdf(["Receipt", "Amount: $5"]))
    assert detect_document_type(nothing, LOGISTICS).name == "purchase_order"
    assert detect_document_type(nothing, default_invoice_config()).name == "invoice"


@pytest.mark.parametrize("filename", ["contoso-purchase-order.pdf", "contoso-delivery-note.pdf"])
def test_contoso_examples_extract_cleanly(filename: str) -> None:
    case = example_cases()[filename]
    data = (EXAMPLES / filename).read_bytes()
    assert data == case.pdf(), "committed example drifted from the generator"
    result = MockInvoiceProvider().extract(data, LOGISTICS)
    assert result.document_type == case.document_type
    assert {field.name: field.value for field in result.fields} == case.truth
    type_spec = LOGISTICS.document_type(case.document_type)
    assert type_spec is not None
    evaluation = evaluate(result.fields, result.pages, type_spec)
    assert [item.name for item in evaluation.fields if item.status != "auto"] == []
    assert all(rule.passed in (True, None) for rule in evaluation.rule_results)


@pytest.mark.parametrize("document_type", DOCUMENT_TYPES)
def test_rules_provider_extracts_synthetic_documents_of_each_type(document_type: str) -> None:
    rng = random.Random(3)
    for index in range(1, 9):
        case = build_case(rng, index, document_type, "clean")
        result = MockInvoiceProvider().extract(case.pdf(), template_config(case.template))
        assert result.document_type == document_type, case.name
        assert {field.name: field.value for field in result.fields} == case.truth, case.name
