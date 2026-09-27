"""Near-duplicate detection: the identity triple, effective values, links and forced review."""

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from scripts.generate_demo_invoice import invoice_pdf
from sqlalchemy import Engine, create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import near_duplicates, review_service
from app.confidence import evaluate
from app.intake_models import DocumentLink
from app.llm.provider import ExtractedValue, MockInvoiceProvider
from app.main import app
from app.models import Base, Document, Membership, Organization, User, WorkflowConfig
from app.storage import get_store
from app.worker import process_one
from app.workflow_config import default_invoice_config, default_logistics_config
from app.workflow_models import FieldCorrection, InvoiceMetadata
from tests.conftest import TenantFactory, postgres
from tests.test_documents import MemoryStore, audit_events, tenant_login, threshold_config, upload
from tests.test_review import add_fields, make_document

NOW = datetime.now(UTC).replace(microsecond=0)
INVOICE = default_invoice_config().document_types[0]
PURCHASE_ORDER = default_logistics_config().document_types[0]
BASE = {"vendor": "Harbor Supply", "invoice_number": "HS-1001", "total": "$110.00"}
TYPES = {"invoice_number": "identifier", "po_number": "identifier", "total": "money"}


@pytest.fixture
def engine() -> Iterator[Engine]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


def seed_org(session: Session) -> tuple[uuid.UUID, dict[str, uuid.UUID]]:
    org_id = uuid.uuid4()
    users = {"admin": uuid.uuid4(), "member": uuid.uuid4()}
    session.add(Organization(id=org_id, slug=f"dup-{org_id.hex[:6]}", name="Duplicates"))
    for role, user_id in users.items():
        session.add(
            User(id=user_id, email=f"{role}-{user_id.hex[:6]}@example.com", password_hash="x")
        )
    session.flush()
    for role, user_id in users.items():
        session.add(Membership(org_id=org_id, user_id=user_id, role=role, status="active"))
    session.add(
        WorkflowConfig(
            org_id=org_id, version=1, config_json=default_invoice_config().model_dump_json()
        )
    )
    session.flush()
    return org_id, users


def stored_document(
    session: Session,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    filename: str,
    values: dict[str, str],
    *,
    status: str = "approved",
    document_type: str = "invoice",
) -> tuple[Document, dict[str, uuid.UUID]]:
    document = make_document(org_id, user_id, filename, status, NOW - timedelta(days=1))
    document.document_type = document_type
    session.add(document)
    session.flush()
    fields = add_fields(
        session,
        org_id,
        document,
        [{"name": n, "value": v, "field_type": TYPES.get(n, "text")} for n, v in values.items()],
        NOW - timedelta(days=1),
    )
    return document, {field.name: field.id for field in fields}


def candidate_document(session: Session, org_id: uuid.UUID, user_id: uuid.UUID) -> Document:
    document = make_document(org_id, user_id, "b.pdf", "validating", NOW)
    session.add(document)
    session.flush()
    return document


def test_find_matches_only_the_full_identity_triple_within_the_type(engine: Engine) -> None:
    with Session(engine) as session:
        org_id, users = seed_org(session)
        original, _ = stored_document(session, org_id, users["member"], "a.pdf", BASE)
        stored_document(session, org_id, users["member"], "failed.pdf", BASE, status="failed")
        order, _ = stored_document(
            session,
            org_id,
            users["member"],
            "po.pdf",
            {"supplier": "Harbor Supply", "po_number": "HS-1001", "total": "$110.00"},
            document_type="purchase_order",
        )
        candidate = candidate_document(session, org_id, users["member"])

        def find(values: dict[str, str]) -> list[uuid.UUID]:
            found = near_duplicates.find_near_duplicates(session, candidate, INVOICE, values)
            return [item.id for item in found]

        assert find(BASE) == [original.id]
        assert find({**BASE, "vendor": "  harbor SUPPLY "}) == [original.id]
        assert find({**BASE, "total": "USD 110.00"}) == [original.id]
        assert find({**BASE, "total": "$111.00"}) == []
        assert find({**BASE, "vendor": "Other Vendor"}) == []
        assert find({**BASE, "invoice_number": "HS-1002"}) == []
        assert find({"vendor": "Harbor Supply", "total": "$110.00"}) == []
        candidate.document_type = "purchase_order"
        session.flush()
        matches = near_duplicates.find_near_duplicates(
            session,
            candidate,
            PURCHASE_ORDER,
            {"supplier": "Harbor Supply", "po_number": "HS-1001", "total": "$110.00"},
        )
        assert [item.id for item in matches] == [order.id]


def test_corrections_on_earlier_documents_are_the_values_compared(engine: Engine) -> None:
    with Session(engine) as session:
        org_id, users = seed_org(session)
        original, field_ids = stored_document(session, org_id, users["member"], "a.pdf", BASE)
        session.add(
            FieldCorrection(
                org_id=org_id,
                document_id=original.id,
                field_id=field_ids["invoice_number"],
                field_name="invoice_number",
                kind="edit",
                before_value="HS-1001",
                after_value="HS-1002",
                reviewer_user_id=users["admin"],
                created_at=NOW,
            )
        )
        session.flush()
        candidate = candidate_document(session, org_id, users["member"])
        assert near_duplicates.find_near_duplicates(session, candidate, INVOICE, BASE) == []
        corrected = near_duplicates.find_near_duplicates(
            session, candidate, INVOICE, {**BASE, "invoice_number": "HS-1002"}
        )
        assert [item.id for item in corrected] == [original.id]


def test_flag_links_both_ways_forces_review_and_is_idempotent(engine: Engine) -> None:
    values = [
        ExtractedValue("vendor", "Harbor Supply", "Vendor: Harbor Supply", 1, 1.0),
        ExtractedValue("invoice_number", "HS-1001", "Invoice Number: HS-1001", 1, 1.0),
        ExtractedValue("invoice_date", "2026-09-01", "Invoice Date: 2026-09-01", 1, 1.0),
        ExtractedValue("total", "$110.00", "Total: $110.00", 1, 1.0),
    ]
    pages = ["\n".join(item.evidence for item in values)]
    with Session(engine) as session:
        org_id, users = seed_org(session)
        original, _ = stored_document(session, org_id, users["member"], "a.pdf", BASE)
        candidate = candidate_document(session, org_id, users["member"])
        evaluation = evaluate(values, pages, INVOICE)
        assert all(item.status == "auto" for item in evaluation.fields)
        matches = near_duplicates.flag_near_duplicates(session, candidate, INVOICE, evaluation, NOW)
        assert [item.id for item in matches] == [original.id]
        number = next(item for item in evaluation.fields if item.name == "invoice_number")
        assert number.status == "needs_review"
        assert number.reasons == ["Possible duplicate of a.pdf"]
        assert all(item.status == "auto" for item in evaluation.fields if item is not number)
        session.flush()
        links = session.scalars(select(DocumentLink).where(DocumentLink.org_id == org_id)).all()
        assert {(link.document_id, link.related_document_id, link.kind) for link in links} == {
            (candidate.id, original.id, "near_duplicate"),
            (original.id, candidate.id, "near_duplicate"),
        }
        again = near_duplicates.flag_near_duplicates(
            session, candidate, INVOICE, evaluate(values, pages, INVOICE), NOW
        )
        session.flush()
        assert [item.id for item in again] == [original.id]
        assert session.scalar(select(func.count(DocumentLink.id))) == 2


def test_detail_lists_only_the_near_duplicates_the_viewer_may_see(engine: Engine) -> None:
    with Session(engine) as session:
        org_id, users = seed_org(session)
        original, _ = stored_document(session, org_id, users["admin"], "a.pdf", BASE)
        session.add(
            InvoiceMetadata(document_id=original.id, org_id=org_id, visibility="restricted")
        )
        candidate = candidate_document(session, org_id, users["member"])
        near_duplicates.link_near_duplicates(session, candidate, [original], NOW)
        session.flush()
        admin_view = review_service.document_detail(session, candidate, (users["admin"], "admin"))
        assert [
            (ref.document_id, ref.filename, ref.status) for ref in admin_view.near_duplicates
        ] == [(original.id, "a.pdf", "approved")]
        member_view = review_service.document_detail(
            session, candidate, (users["member"], "member")
        )
        assert member_view.near_duplicates == []
        unscoped = review_service.document_detail(session, candidate)
        assert [ref.document_id for ref in unscoped.near_duplicates] == [original.id]
        assert unscoped.context_text is None and unscoped.source == "upload"


@postgres
def test_second_upload_of_the_same_invoice_is_linked_and_reviewed(
    monkeypatch: pytest.MonkeyPatch, make_tenant: TenantFactory
) -> None:
    monkeypatch.setattr("app.worker.get_provider", MockInvoiceProvider)
    tenant = make_tenant(threshold_config())
    store = MemoryStore()
    app.dependency_overrides[get_store] = lambda: store
    try:
        with TestClient(app) as client:
            tenant_login(client, tenant, "member")
            first_pdf = invoice_pdf(invoice_number="DUP-0001", total="$88.00")
            first = uuid.UUID(upload(client, "first.pdf", first_pdf)["id"])
            assert process_one(store, first) is True
            assert client.get(f"/v1/documents/{first}").json()["status"] == "auto_approved"

            second_pdf = invoice_pdf(
                invoice_number="DUP-0001", total="$88.00", extra_lines={"Due Date": "2026-10-30"}
            )
            second = uuid.UUID(upload(client, "second.pdf", second_pdf)["id"])
            assert process_one(store, second) is True
            body = client.get(f"/v1/documents/{second}").json()
            assert body["status"] == "needs_review" and body["flagged_count"] == 1
            number = next(field for field in body["fields"] if field["name"] == "invoice_number")
            assert number["status"] == "needs_review"
            assert "Possible duplicate of first.pdf" in number["reasons"]
            assert [ref["document_id"] for ref in body["near_duplicates"]] == [str(first)]
            assert body["near_duplicates"][0]["filename"] == "first.pdf"
            first_body = client.get(f"/v1/documents/{first}").json()
            assert [ref["document_id"] for ref in first_body["near_duplicates"]] == [str(second)]
            events = dict(audit_events(tenant.org_id, second))
            assert events["document.near_duplicate"]["related_document_ids"] == [str(first)]
            assert events["document.needs_review"]["near_duplicates"] == [str(first)]
            assert events["document.needs_review"]["flagged_fields"] == ["invoice_number"]
            queue = client.get("/v1/review/queue").json()
            assert [row["document_id"] for row in queue] == [str(second)]
    finally:
        del app.dependency_overrides[get_store]
