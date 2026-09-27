"""Per-organization memory: profiles, few-shots, priors, retrieval order and tenant isolation."""

import json
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from scripts.generate_demo_invoice import invoice_pdf
from sqlalchemy import create_engine, select
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import memory
from app.db import SessionLocal, set_org_context
from app.learning_models import MemoryItem
from app.llm.embeddings import LocalHashEmbedder, cosine_similarity, hash_embedding
from app.llm.provider import ExtractedValue, MockInvoiceProvider
from app.llm.router import ModelRouter
from app.main import app
from app.memory import (
    Correction,
    VendorProfile,
    context_for,
    detect_vendor,
    format_pattern,
    learn,
    normalize_vendor,
    prior_for,
    priors_for,
)
from app.models import Base, Organization
from app.storage import get_store
from app.worker import process_one
from app.workflow_config import default_invoice_config
from tests.conftest import TenantFactory, postgres
from tests.test_documents import MemoryStore, tenant_login, upload

CONFIG = default_invoice_config()
INVOICE = CONFIG.document_types[0]
EMBEDDER = LocalHashEmbedder()


@pytest.fixture
def store() -> Iterator[tuple[Session, uuid.UUID, uuid.UUID]]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    org_a, org_b = uuid.uuid4(), uuid.uuid4()
    with Session(engine) as session:
        session.add_all(
            [
                Organization(id=org_a, slug="mem-a", name="A"),
                Organization(id=org_b, slug="mem-b", name="B"),
            ]
        )
        session.commit()
        yield session, org_a, org_b
    engine.dispose()


def test_vendor_keys_and_format_patterns() -> None:
    assert normalize_vendor("  Harbor  Supply, Co.  ") == "harbor supply co"
    assert normalize_vendor("HARBOR SUPPLY CO") == normalize_vendor("harbor supply co")
    assert format_pattern("05-Mar-26") == "99-AAA-99"
    assert format_pattern("$1,234.50") == "$9,999.99"
    assert format_pattern("INV-2026-0001") == "AAA-9999-9999"
    assert format_pattern(" USD ") == "AAA"


def test_embeddings_are_deterministic_normalized_and_similar_for_shared_text() -> None:
    vector = hash_embedding("Vendor: Harbor Supply Co Total: $110.00")
    assert len(vector) == 256
    assert vector == hash_embedding("Vendor: Harbor Supply Co Total: $110.00")
    assert round(sum(value * value for value in vector), 6) == 1.0
    same_vendor = hash_embedding("Invoice from Harbor Supply Co, total $120.00")
    other = hash_embedding("Delivery note Cedar Freight Lines packages 4")
    assert cosine_similarity(vector, same_vendor) > cosine_similarity(vector, other)
    assert hash_embedding("") == [0.0] * 256
    assert EMBEDDER.embed("x", org_id=None, document_id=None, trace_id=None) == hash_embedding("x")


def test_memory_prior_values_follow_the_profile() -> None:
    profile = VendorProfile("harbor supply co", "Harbor Supply Co")
    profile.absorb(
        {"vendor": "Harbor Supply Co", "total": "$110.00", "currency": "USD", "due_date": ""},
        INVOICE,
    )
    assert profile.typical_currency == "USD" and profile.documents == 1
    assert profile.patterns == {
        "vendor": {"AAAAAA AAAAAA AA": 1},
        "total": {"$999.99": 1},
        "currency": {"AAA": 1},
    }
    assert prior_for(None, "currency", "currency", "USD") is None
    assert prior_for(profile, "currency", "currency", "usd") == 1.0
    assert prior_for(profile, "currency", "currency", "EUR") == 0.3
    assert prior_for(profile, "money", "total", "$999.00") == 1.0
    assert prior_for(profile, "money", "total", "$1,999.00") == 0.5
    assert prior_for(profile, "date", "invoice_date", "2026-01-01") is None
    fields = [
        ExtractedValue("vendor", "Harbor Supply Co", "Vendor: Harbor Supply Co", 1),
        ExtractedValue("total", "$120.00", "Total: $120.00", 1),
        ExtractedValue("currency", "GBP", "Currency: GBP", 1),
        ExtractedValue("invoice_date", "2026-01-01", "Invoice Date: 2026-01-01", 1),
        ExtractedValue("unknown_field", "x", "x", 1),
    ]
    assert priors_for(profile, INVOICE, fields) == {
        "vendor": 1.0,
        "total": 1.0,
        "currency": 0.3,
        "invoice_date": None,
    }
    assert priors_for(None, INVOICE, fields) == {
        "vendor": None,
        "total": None,
        "currency": None,
        "invoice_date": None,
    }
    # The most common currency wins once several were seen.
    profile.absorb({"currency": "EUR"}, INVOICE)
    profile.absorb({"currency": "EUR"}, INVOICE)
    assert profile.typical_currency == "EUR" and profile.currency_counts == {"USD": 1, "EUR": 2}


def test_learn_upserts_the_profile_and_deduplicates_few_shots(
    store: tuple[Session, uuid.UUID, uuid.UUID],
) -> None:
    session, org_a, _ = store
    values = {"vendor": "Harbor Supply Co", "total": "$110.00", "currency": "USD"}
    first = Correction("total", "$11O.OO", "$110.00", "Total: $11O.OO")
    profile, written = learn(
        session, org_a, vendor="Harbor Supply Co", type_spec=INVOICE, values=values,
        corrections=[first], embedder=EMBEDDER,
    )
    assert written == 1 and profile.documents == 1
    profile, written = learn(
        session, org_a, vendor="HARBOR SUPPLY CO", type_spec=INVOICE, values=values,
        corrections=[first, Correction("vendor", "Harbor", "Harbor Supply Co", "Vendor: Harbor")],
        embedder=EMBEDDER,
    )
    assert written == 2 and profile.documents == 2 and profile.name == "HARBOR SUPPLY CO"
    rows = session.scalars(select(MemoryItem).order_by(MemoryItem.kind, MemoryItem.id)).all()
    assert [(row.kind, row.key) for row in rows] == [
        ("few_shot", "harbor supply co"),
        ("few_shot", "harbor supply co"),
        ("vendor_profile", "harbor supply co"),
    ]
    # The repeated correction refreshed the stored example (vendor spelling included).
    examples = [json.loads(row.content_json) for row in rows[:2]]
    content = next(example for example in examples if example["field"] == "total")
    assert content == {
        "vendor": "HARBOR SUPPLY CO",
        "field": "total",
        "wrong_value": "$11O.OO",
        "correct_value": "$110.00",
        "snippet": "Total: $11O.OO",
        "document_type": "invoice",
    }
    assert all(row.embedding is not None and len(row.embedding) == 256 for row in rows[:2])
    stored = json.loads(rows[2].content_json)
    assert stored["documents"] == 2 and stored["typical_currency"] == "USD"
    assert stored["patterns"]["total"] == {"$999.99": 2}
    # Corrections for unknown fields are ignored; a vendorless call is refused.
    _, ignored = learn(
        session, org_a, vendor="Harbor Supply Co", type_spec=INVOICE, values=values,
        corrections=[Correction("mystery", "a", "b", "c")], embedder=EMBEDDER,
    )
    assert ignored == 0
    with pytest.raises(ValueError):
        learn(session, org_a, vendor="  ", type_spec=INVOICE, values=values)


def test_few_shots_per_vendor_are_bounded_by_reusing_the_oldest_row(
    store: tuple[Session, uuid.UUID, uuid.UUID],
) -> None:
    session, org_a, _ = store
    base = datetime(2026, 1, 1, tzinfo=UTC)
    for index in range(memory.MAX_FEW_SHOTS_PER_VENDOR + 2):
        learn(
            session, org_a, vendor="Maple Office", type_spec=INVOICE,
            values={"vendor": "Maple Office"},
            corrections=[Correction("total", str(index), "$1.00", f"Total: {index}")],
            embedder=EMBEDDER, now=base + timedelta(minutes=index),
        )
    rows = session.scalars(select(MemoryItem).where(MemoryItem.kind == "few_shot")).all()
    assert len(rows) == memory.MAX_FEW_SHOTS_PER_VENDOR
    wrong = {json.loads(row.content_json)["wrong_value"] for row in rows}
    assert "0" not in wrong and "1" not in wrong and "21" in wrong


def test_retrieval_prefers_the_vendor_then_similar_text_and_never_crosses_orgs(
    store: tuple[Session, uuid.UUID, uuid.UUID],
) -> None:
    session, org_a, org_b = store
    now = datetime(2026, 5, 1, tzinfo=UTC)

    def add(org: uuid.UUID, vendor: str, field: str, text: str, minutes: int) -> None:
        learn(
            session, org, vendor=vendor, type_spec=INVOICE, values={"vendor": vendor},
            corrections=[Correction(field, "x", "y", text)], embedder=EMBEDDER,
            now=now + timedelta(minutes=minutes),
        )

    add(org_a, "Harbor Supply Co", "total", "Total: $110.00 payable on receipt", 0)
    add(org_a, "Harbor Supply Co", "invoice_date", "Invoice Date: 05-Mar-26", 1)
    add(org_a, "Granite Tooling", "total", "Total: $99.00 freight included", 2)
    add(org_a, "Granite Tooling", "po_number", "PO Number: PO-77 freight", 3)
    add(org_a, "Granite Tooling", "tax", "Tax: $5.00 tooling deposit", 4)
    add(org_b, "Harbor Supply Co", "total", "Total: $110.00 payable on receipt", 5)
    page = ["Invoice\nVendor: Harbor Supply Co\nTotal: $120.00 payable on receipt\n"]
    context = context_for(session, org_a, page, CONFIG, embedder=EMBEDDER)
    assert context.detected_vendor == "harbor supply co"
    assert set(context.profiles) == {"harbor supply co"}
    assert [(example.vendor, example.field) for example in context.examples] == [
        ("Harbor Supply Co", "total"),
        ("Harbor Supply Co", "invoice_date"),
        ("Granite Tooling", "total"),
    ]
    other = context_for(session, org_b, page, CONFIG, embedder=EMBEDDER)
    assert [(example.vendor, example.field) for example in other.examples] == [
        ("Harbor Supply Co", "total")
    ]
    unknown = context_for(
        session, org_a, ["Delivery note from Cedar Freight Lines"], CONFIG, embedder=EMBEDDER
    )
    assert unknown.detected_vendor is None and unknown.profiles == {}
    assert len(unknown.examples) == 3
    assert context.profile_for("HARBOR SUPPLY CO") is not None
    assert context.profile_for("Nobody") is context.profiles["harbor supply co"]
    assert memory.EMPTY_CONTEXT.profile_for("Harbor Supply Co") is None
    assert detect_vendor("bill from granite tooling ltd", ["granite", "granite tooling"]) == (
        "granite tooling"
    )
    assert memory.profile_for_vendor(session, org_b, "Granite Tooling") is None
    assert memory.profile_for_vendor(session, org_a, "Granite Tooling") is not None


def test_router_applies_memory_priors_from_the_matching_profile(
    store: tuple[Session, uuid.UUID, uuid.UUID],
) -> None:
    session, org_a, _ = store
    learn(
        session, org_a, vendor="Northwind Traders", type_spec=INVOICE,
        values={"vendor": "Northwind Traders", "total": "$123.45", "currency": "USD"},
        embedder=EMBEDDER,
    )
    page = (
        "Invoice\nVendor: Northwind Traders\nInvoice Number: NW-1\nInvoice Date: 2026-09-26\n"
        "Total: $1,999.00\nCurrency: EUR\n"
    )
    context = context_for(session, org_a, [page], CONFIG, embedder=EMBEDDER)
    assessment = ModelRouter(MockInvoiceProvider(recorder=lambda o: None)).run(
        [page], CONFIG, None, context
    )
    assert assessment.vendor_key == "northwind traders"
    assert assessment.memory_prior == {
        "vendor": 1.0,
        "invoice_number": None,
        "invoice_date": None,
        "total": 0.5,
        "currency": 0.3,
    }
    by_name = {item.name: item for item in assessment.evaluation.fields}
    assert by_name["currency"].signals["memory_prior"] == 0.3
    assert by_name["total"].signals["memory_prior"] == 0.5
    assert by_name["vendor"].signals["memory_prior"] == 1.0
    assert by_name["invoice_number"].signals["memory_prior"] is None
    # A 0.3 prior at weight 0.05 nudges but never flags a field that passed every other check.
    assert by_name["currency"].status == "auto"
    assert by_name["currency"].confidence == round(
        (0.35 + 0.25 + 0.05 * 0.3 + 0.05) / (0.35 + 0.25 + 0.05 + 0.05), 4
    )


@postgres
def test_corrections_and_approval_update_memory_under_rls(
    monkeypatch: pytest.MonkeyPatch, make_tenant: TenantFactory
) -> None:
    monkeypatch.setattr("app.worker.get_provider", MockInvoiceProvider)
    tenant, other = make_tenant(), make_tenant()
    store = MemoryStore()
    app.dependency_overrides[get_store] = lambda: store
    try:
        with TestClient(app) as client:
            tenant_login(client, tenant, "member")
            document_id = uuid.UUID(
                upload(
                    client,
                    "learn.pdf",
                    invoice_pdf(
                        invoice_number="LEARN-1",
                        vendor="Harbor Supply Co",
                        total="$110.00",
                        extra_lines={"Subtotal": "$100.00", "Tax": "$10.00", "Currency": "USD"},
                    ),
                )["id"]
            )
            assert process_one(store, document_id) is True
            tenant_login(client, tenant, "reviewer")
            path = f"/v1/documents/{document_id}"
            fields = {field["name"]: field for field in client.get(path).json()["fields"]}
            edited = client.post(
                f"{path}/fields/{fields['invoice_date']['id']}",
                json={"version": 0, "action": "edit", "value": "26-Sep-26"},
            )
            assert edited.status_code == 200, edited.text
            with SessionLocal() as session:
                set_org_context(session, tenant.org_id)
                rows = session.scalars(select(MemoryItem).order_by(MemoryItem.kind)).all()
                assert [(row.kind, row.key) for row in rows] == [
                    ("few_shot", "harbor supply co"),
                    ("vendor_profile", "harbor supply co"),
                ]
                example = json.loads(rows[0].content_json)
                assert (example["field"], example["wrong_value"], example["correct_value"]) == (
                    "invoice_date",
                    "2026-09-26",
                    "26-Sep-26",
                )
                assert example["snippet"] == "Invoice Date: 2026-09-26"
                assert rows[0].embedding is not None and len(rows[0].embedding) == 256
                profile = json.loads(rows[1].content_json)
                assert profile["documents"] == 1 and profile["typical_currency"] == "USD"
                assert profile["patterns"]["invoice_date"] == {"99-AAA-99": 1}
            accepted = client.post(
                f"{path}/fields/{fields['total']['id']}", json={"version": 1, "action": "accept"}
            )
            assert accepted.status_code == 200, accepted.text
            approved = client.post(f"{path}/review", json={"version": 2, "decision": "approve"})
            assert approved.status_code == 200, approved.text
            with SessionLocal() as session:
                set_org_context(session, tenant.org_id)
                rows = session.scalars(select(MemoryItem).order_by(MemoryItem.kind)).all()
                assert [row.kind for row in rows] == ["few_shot", "vendor_profile"]
                profile = json.loads(rows[1].content_json)
                assert profile["documents"] == 2
                assert profile["last_values"]["invoice_date"] == "26-Sep-26"
                # The same page text now retrieves the example, under this tenant only.
                context = context_for(
                    session,
                    tenant.org_id,
                    ["Invoice\nVendor: Harbor Supply Co\nTotal: $110.00"],
                    CONFIG,
                    embedder=EMBEDDER,
                )
                assert [example.field for example in context.examples] == ["invoice_date"]
                assert context.detected_vendor == "harbor supply co"
            with SessionLocal() as session:
                set_org_context(session, other.org_id)
                assert session.scalars(select(MemoryItem)).all() == []
                context = context_for(
                    session,
                    other.org_id,
                    ["Invoice\nVendor: Harbor Supply Co\nTotal: $110.00"],
                    CONFIG,
                    embedder=EMBEDDER,
                )
                assert context.examples == [] and context.profiles == {}
                # Writing under the wrong tenant context is rejected by row-level security.
                session.add(
                    MemoryItem(
                        org_id=tenant.org_id,
                        kind="vendor_profile",
                        key="smuggled",
                        content_json="{}",
                    )
                )
                with pytest.raises(ProgrammingError):
                    session.flush()
                session.rollback()
    finally:
        del app.dependency_overrides[get_store]
