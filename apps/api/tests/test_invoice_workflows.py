"""Behavior checks for review, tenant isolation, sharing and exact money summaries."""

import json
import os
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, event, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.auth import current_session
from app.db import normalize_database_url, set_org_context
from app.invoice_workflows import accessible_document_clause, can_access_document, router
from app.models import (
    AuditEvent,
    Base,
    Document,
    ExtractedField,
    ExtractionRun,
    Membership,
    Organization,
    User,
)
from app.workflow_models import InvoiceCategory, InvoiceComment, InvoiceMetadata, InvoiceReview


@dataclass
class Workspace:
    client: TestClient
    engine: Engine
    actors: dict[str, uuid.UUID]
    org_id: uuid.UUID
    other_org_id: uuid.UUID
    document_id: uuid.UUID
    other_document_id: uuid.UUID
    actor: str = "admin"

    @property
    def path(self) -> str:
        return f"/v1/documents/{self.document_id}"

    def metadata(self, **changes: object) -> dict[str, object]:
        version = self.client.get(f"{self.path}/workspace").json()["version"]
        response = self.client.post(f"{self.path}/metadata", json={"version": version, **changes})
        assert response.status_code == 200, response.text
        return dict(response.json())

    def share(self, targets: list[uuid.UUID]) -> dict[str, object]:
        version = self.client.get(f"{self.path}/workspace").json()["version"]
        response = self.client.post(
            f"{self.path}/sharing",
            json={
                "version": version,
                "visibility": "restricted",
                "user_ids": list(map(str, targets)),
            },
        )
        assert response.status_code == 200, response.text
        return dict(response.json())


def make_document(
    org_id: uuid.UUID, user_id: uuid.UUID, *, status: str = "needs_review"
) -> Document:
    identity = uuid.uuid4()
    return Document(
        id=identity,
        org_id=org_id,
        uploaded_by=user_id,
        filename=f"{identity}.pdf",
        content_type="application/pdf",
        size_bytes=100,
        content_hash=identity.hex,
        storage_key=f"{org_id}/{identity}.pdf",
        workflow_config_version=1,
        status=status,
    )


@pytest.fixture
def workspace() -> Iterator[Workspace]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )

    @event.listens_for(engine, "connect")
    def foreign_keys(connection: object, _: object) -> None:
        # sqlite3.Connection is not exported by SQLAlchemy's generic Engine type.
        from sqlite3 import Connection

        assert isinstance(connection, Connection)
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    org_id, other_org = uuid.uuid4(), uuid.uuid4()
    actors = {
        name: uuid.uuid4()
        for name in (
            "admin",
            "reviewer",
            "reviewer2",
            "member",
            "viewer",
            "pending",
            "external",
        )
    }
    with Session(engine) as session:
        session.add_all(
            [
                Organization(id=org_id, slug="workspace", name="Workspace"),
                Organization(id=other_org, slug="outside", name="Outside"),
            ]
        )
        for name, user_id in actors.items():
            session.add(User(id=user_id, email=f"{name}@example.com", password_hash="not-used"))
        session.flush()
        for name, user_id in actors.items():
            session.add(
                Membership(
                    org_id=other_org if name == "external" else org_id,
                    user_id=user_id,
                    role="reviewer"
                    if name == "reviewer2"
                    else "member"
                    if name == "pending"
                    else "admin"
                    if name == "external"
                    else name,
                    status="pending" if name == "pending" else "active",
                )
            )
        session.flush()
        document = make_document(org_id, actors["member"])
        other_document = make_document(other_org, actors["external"])
        session.add_all([document, other_document])
        session.flush()
        run = ExtractionRun(
            org_id=org_id,
            document_id=document.id,
            provider="mock",
            model="mock",
            prompt_version="test",
            raw_json="{}",
        )
        session.add(run)
        session.flush()
        session.add_all(
            [
                ExtractedField(
                    org_id=org_id,
                    document_id=document.id,
                    extraction_run_id=run.id,
                    name=name,
                    value=value,
                    evidence=evidence,
                    page_number=1,
                )
                for name, value, evidence in [
                    ("vendor", "Harbor Supply", "Vendor: Harbor Supply"),
                    ("total", "$19.25", "Total: $19.25"),
                    ("invoice_date", "2026-09-26", "Date: 2026-09-26"),
                ]
            ]
        )
        session.commit()
        document_id, other_document_id = document.id, other_document.id
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        state = Workspace(client, engine, actors, org_id, other_org, document_id, other_document_id)

        def context() -> Iterator[tuple[Session, User, Organization, Membership]]:
            with Session(engine, expire_on_commit=False) as session:
                user = session.get(User, actors[state.actor])
                assert user is not None
                membership = session.scalar(select(Membership).where(Membership.user_id == user.id))
                assert membership is not None
                org = session.get(Organization, membership.org_id)
                assert org is not None
                yield session, user, org, membership

        app.dependency_overrides[current_session] = context
        yield state
    engine.dispose()


def test_category_admin_management_versioning_and_archive(workspace: Workspace) -> None:
    client = workspace.client
    workspace.actor = "member"
    assert client.post("/v1/categories", json={"name": "Travel"}).status_code == 403
    workspace.actor = "admin"
    response = client.post("/v1/categories", json={"name": " Travel ", "description": "Trips"})
    assert response.status_code == 201
    category = response.json()
    assert category["name"] == "Travel"
    assert client.post("/v1/categories", json={"name": "travel"}).status_code == 409
    assert (
        client.post(
            f"/v1/categories/{category['id']}",
            json={
                "version": 3,
                "active": False,
            },
        ).status_code
        == 409
    )
    workspace.metadata(category_id=category["id"])
    archived = client.post(f"/v1/categories/{category['id']}", json={"version": 1, "active": False})
    assert archived.status_code == 200
    assert archived.json()["version"] == 2
    assert client.get(f"{workspace.path}/workspace").json()["category_id"] == category["id"]
    # Keeping a historic category must not prevent verification after it is archived.
    workspace.metadata(category_id=category["id"], verified_amount="19.25", currency="USD")
    workspace.metadata(category_id=None)
    denied = client.post(
        f"{workspace.path}/metadata",
        json={
            "version": 3,
            "category_id": category["id"],
        },
    )
    assert denied.status_code == 400
    workspace.actor = "external"
    assert client.get("/v1/categories").json() == []
    assert (
        client.post(
            f"/v1/categories/{category['id']}",
            json={
                "version": 2,
                "active": True,
            },
        ).status_code
        == 404
    )


def test_verification_requires_explicit_currency_and_keeps_extraction(workspace: Workspace) -> None:
    client = workspace.client
    for changes in ({"verified_amount": "19.25"}, {"currency": "USD"}):
        assert (
            client.post(
                f"{workspace.path}/metadata",
                json={
                    "version": 0,
                    **changes,
                },
            ).status_code
            == 422
        )
    for amount, currency in (
        ("NaN", "USD"),
        ("-1", "USD"),
        ("1.00001", "USD"),
        ("10", "$"),
        ("10", "XYZ"),
    ):
        assert (
            client.post(
                f"{workspace.path}/metadata",
                json={
                    "version": 0,
                    "verified_amount": amount,
                    "currency": currency,
                },
            ).status_code
            == 422
        )
    edited = workspace.metadata(verified_amount="21.75", currency="usd")
    assert edited["currency"] == "USD"
    assert Decimal(str(edited["verified_amount"])) == Decimal("21.75")
    assert (
        client.post(
            f"{workspace.path}/metadata",
            json={
                "version": 0,
                "verified_amount": "22",
                "currency": "USD",
            },
        ).status_code
        == 409
    )
    with Session(workspace.engine) as session:
        fields = session.scalars(
            select(ExtractedField).where(
                ExtractedField.document_id == workspace.document_id,
            )
        ).all()
        assert next(row.value for row in fields if row.name == "total") == "$19.25"
        audit = session.scalar(
            select(AuditEvent).where(
                AuditEvent.event_type == "invoice.metadata_updated",
            )
        )
        assert audit is not None
        assert json.loads(audit.detail_json)["changes"]["verified_amount"] == "21.75"


def test_review_assignment_transitions_and_stale_decisions(workspace: Workspace) -> None:
    client = workspace.client
    approve = {"version": 0, "decision": "approve"}
    assert client.post(f"{workspace.path}/review", json=approve).status_code == 422
    workspace.metadata(
        assigned_reviewer_id=str(workspace.actors["reviewer"]),
        verified_amount="19.25",
        currency="USD",
    )
    workspace.actor = "reviewer2"
    assert not client.get(f"{workspace.path}/workspace").json()["capabilities"]["can_review"]
    assert (
        client.post(
            f"{workspace.path}/review",
            json={
                "version": 1,
                "decision": "approve",
            },
        ).status_code
        == 403
    )
    workspace.actor = "reviewer"
    assert (
        client.post(
            f"{workspace.path}/metadata",
            json={
                "version": 1,
                "assigned_reviewer_id": None,
            },
        ).status_code
        == 403
    )
    approved = client.post(f"{workspace.path}/review", json={"version": 1, "decision": "approve"})
    assert approved.status_code == 200
    assert approved.json()["version"] == 2
    assert not approved.json()["capabilities"]["can_edit"]
    assert (
        client.post(
            f"{workspace.path}/review",
            json={
                "version": 1,
                "decision": "reject",
                "comment": "Stale request",
            },
        ).status_code
        == 409
    )
    assert (
        client.post(
            f"{workspace.path}/metadata",
            json={
                "version": 2,
                "verified_amount": "999",
                "currency": "USD",
            },
        ).status_code
        == 409
    )
    assert (
        client.post(
            f"{workspace.path}/review",
            json={
                "version": 2,
                "decision": "reopen",
            },
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"{workspace.path}/review",
            json={
                "version": 3,
                "decision": "reject",
                "comment": "   ",
            },
        ).status_code
        == 422
    )
    rejected = client.post(
        f"{workspace.path}/review",
        json={
            "version": 3,
            "decision": "reject",
            "comment": "Duplicate service charge",
        },
    )
    assert rejected.status_code == 200
    assert [item["decision"] for item in rejected.json()["reviews"]] == [
        "approve",
        "reopen",
        "reject",
    ]
    with Session(workspace.engine) as session:
        document = session.get(Document, workspace.document_id)
        assert document is not None and document.status == "rejected"
        assert len(session.scalars(select(InvoiceReview)).all()) == 3


def test_restricted_sharing_all_access_paths_and_revocation(workspace: Workspace) -> None:
    client = workspace.client
    workspace.actor = "member"
    workspace.share([workspace.actors["reviewer"]])
    assert (
        client.post(f"{workspace.path}/comments", json={"body": "Please check freight"}).status_code
        == 201
    )
    workspace.actor = "reviewer2"
    assert client.get(f"{workspace.path}/workspace").status_code == 404
    assert client.post(f"{workspace.path}/comments", json={"body": "Sneak in"}).status_code == 404
    assert (
        client.post(
            "/v1/workspace/questions",
            json={
                "question": "What is the total?",
                "document_id": str(workspace.document_id),
            },
        ).status_code
        == 404
    )
    assert client.get("/v1/workspace/summary").json()["total_documents"] == 0
    with Session(workspace.engine) as session:
        document = session.get(Document, workspace.document_id)
        assert document is not None
        assert not can_access_document(
            session, workspace.org_id, workspace.actors["reviewer2"], "reviewer", document
        )
        assert (
            session.scalars(
                select(Document).where(
                    accessible_document_clause(
                        workspace.org_id,
                        workspace.actors["reviewer2"],
                        "reviewer",
                    )
                )
            ).all()
            == []
        )
    workspace.actor = "reviewer"
    assert client.get(f"{workspace.path}/workspace").status_code == 200
    assert client.get("/v1/workspace/summary").json()["total_documents"] == 1
    assert (
        client.post(
            f"{workspace.path}/sharing",
            json={
                "version": 1,
                "visibility": "workspace",
                "user_ids": [],
            },
        ).status_code
        == 403
    )
    workspace.actor = "member"
    workspace.share([])
    workspace.actor = "reviewer"
    assert client.get(f"{workspace.path}/workspace").status_code == 404
    workspace.actor = "admin"
    assert client.get(f"{workspace.path}/workspace").status_code == 200
    workspace.metadata(assigned_reviewer_id=str(workspace.actors["reviewer"]))
    workspace.actor = "reviewer"
    assert client.get(f"{workspace.path}/workspace").status_code == 200


def test_cross_org_assignments_and_inactive_grants_are_rejected(workspace: Workspace) -> None:
    client = workspace.client
    for actor in ("external", "pending", "member", "viewer"):
        response = client.post(
            f"{workspace.path}/metadata",
            json={
                "version": 0,
                "assigned_reviewer_id": str(workspace.actors[actor]),
            },
        )
        assert response.status_code == 400
    for actor in ("external", "pending"):
        response = client.post(
            f"{workspace.path}/sharing",
            json={
                "version": 0,
                "visibility": "restricted",
                "user_ids": [str(workspace.actors[actor])],
            },
        )
        assert response.status_code == 400
    members = client.get("/v1/organization/collaborators").json()
    assert all(
        row["email"] not in {"pending@example.com", "external@example.com"} for row in members
    )
    workspace.actor = "external"
    category = client.post("/v1/categories", json={"name": "Private"}).json()
    assert client.get(f"{workspace.path}/workspace").status_code == 404
    workspace.actor = "admin"
    assert (
        client.post(
            f"{workspace.path}/metadata",
            json={
                "version": 0,
                "category_id": category["id"],
            },
        ).status_code
        == 400
    )
    assert client.get(f"/v1/documents/{workspace.other_document_id}/workspace").status_code == 404


def test_member_and_viewer_permissions_and_comment_authorship(workspace: Workspace) -> None:
    client = workspace.client
    workspace.actor = "member"
    assert (
        client.post(
            f"{workspace.path}/metadata",
            json={
                "version": 0,
                "verified_amount": "19.25",
                "currency": "USD",
            },
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"{workspace.path}/review",
            json={
                "version": 0,
                "decision": "approve",
            },
        ).status_code
        == 403
    )
    created = client.post(f"{workspace.path}/comments", json={"body": "  Original note  "})
    assert created.status_code == 201
    assert created.json()["comments"][0]["author_email"] == "member@example.com"
    assert created.json()["comments"][0]["body"] == "Original note"
    assert (
        client.post(
            f"{workspace.path}/comments",
            json={
                "body": "forged",
                "author_user_id": str(workspace.actors["admin"]),
            },
        ).status_code
        == 422
    )
    assert client.post(f"{workspace.path}/comments", json={"body": "  "}).status_code == 422
    workspace.actor = "viewer"
    assert client.get(f"{workspace.path}/workspace").json()["capabilities"] == {
        "can_edit": False,
        "can_review": False,
        "can_share": False,
        "can_assign": False,
        "can_comment": False,
    }
    assert client.post(f"{workspace.path}/comments", json={"body": "No write"}).status_code == 403
    with Session(workspace.engine) as session:
        assert len(session.scalars(select(InvoiceComment)).all()) == 1


def test_all_document_summary_uses_decimal_and_separates_currencies(workspace: Workspace) -> None:
    workspace.metadata(verified_amount="0.10", currency="USD")
    with Session(workspace.engine) as session:
        for index in range(60):
            document = make_document(
                workspace.org_id,
                workspace.actors["admin"],
                status="approved" if index == 0 else "needs_review",
            )
            session.add(document)
            session.flush()
            if index < 2:
                session.add(
                    InvoiceMetadata(
                        document_id=document.id,
                        org_id=workspace.org_id,
                        verified_amount=Decimal("0.20"),
                        currency="USD" if index == 0 else "INR",
                    )
                )
        # Foreign amounts must not influence the caller's result.
        session.add(
            InvoiceMetadata(
                document_id=workspace.other_document_id,
                org_id=workspace.other_org_id,
                verified_amount=Decimal("99999"),
                currency="USD",
            )
        )
        session.commit()
    summary = workspace.client.get("/v1/workspace/summary")
    assert summary.status_code == 200, summary.text
    values = summary.json()
    assert values["total_documents"] == 61
    assert values["excluded_amount_count"] == 58
    assert values["status_counts"] == {"needs_review": 60, "approved": 1}
    amounts = {row["currency"]: row for row in values["amounts_by_currency"]}
    assert Decimal(amounts["USD"]["total"]) == Decimal("0.30")
    assert Decimal(amounts["USD"]["pending_review"]) == Decimal("0.10")
    assert Decimal(amounts["INR"]["total"]) == Decimal("0.20")
    assert values["categories"][0]["document_count"] == 61
    assert values["categories"][0]["excluded_amount_count"] == 58
    assert values["categories"][0]["status_counts"] == values["status_counts"]


def test_questions_are_grounded_current_and_honor_category_and_tenant(workspace: Workspace) -> None:
    client = workspace.client
    first = client.post(
        "/v1/workspace/questions", json={"question": "How many invoices need review?"}
    )
    assert first.status_code == 200
    assert first.json()["supported"] is True
    assert "1 accessible invoice(s)" in first.json()["answer"]
    category = client.post("/v1/categories", json={"name": "Travel"}).json()
    scoped = client.post(
        "/v1/workspace/questions",
        json={
            "question": "Total amount",
            "category_id": category["id"],
        },
    ).json()
    assert scoped["summary"]["total_documents"] == 0
    workspace.metadata(category_id=category["id"], verified_amount="19.25", currency="USD")
    current = client.post(
        "/v1/workspace/questions",
        json={
            "question": "Total amount pending review",
            "category_id": category["id"],
        },
    ).json()
    assert "USD 19.2500" in current["answer"]
    named = client.post("/v1/workspace/questions", json={"question": "Total for Travel"}).json()
    assert named["summary"]["total_documents"] == 1
    assert "USD 19.2500" in named["answer"]
    category_totals = client.post(
        "/v1/workspace/questions",
        json={
            "question": "Show totals by category",
        },
    ).json()
    assert "Travel: 1 invoice(s) (verified USD 19.2500)" in category_totals["answer"]
    evidence = client.post(
        "/v1/workspace/questions",
        json={
            "question": "What are the vendor and invoice date?",
            "document_id": str(workspace.document_id),
        },
    ).json()
    assert evidence["supported"] is True
    assert {row["field"] for row in evidence["citations"]} == {"vendor", "invoice_date"}
    assert any(row["evidence"] == "Vendor: Harbor Supply" for row in evidence["citations"])
    for question in (
        "Predict next year's spend",
        "Total invoices last month",
        "Total for vendor Acme",
        "Total unpaid invoices",
        "Total invoices over 500",
        "Total approved and rejected invoices",
        "Total for Missing Category",
    ):
        unsupported = client.post("/v1/workspace/questions", json={"question": question}).json()
        assert unsupported["supported"] is False
        assert unsupported["summary"] is None
    unsupported_due_date = client.post(
        "/v1/workspace/questions",
        json={
            "question": "What is the due date?",
            "document_id": str(workspace.document_id),
        },
    ).json()
    assert unsupported_due_date["supported"] is False
    workspace.actor = "external"
    assert (
        client.post(
            "/v1/workspace/questions",
            json={
                "question": "Total",
                "category_id": category["id"],
            },
        ).status_code
        == 404
    )


@pytest.mark.parametrize(
    ("question", "invoice_scope"),
    [
        ("Summarize this invoice", True),
        ("What is the total?", True),
        ("Who is the vendor?", True),
        ("How many invoices need review?", False),
        ("What is the total amount pending review?", False),
        ("Show invoice categories", False),
    ],
)
def test_question_examples_shown_in_ui_are_supported(
    workspace: Workspace,
    question: str,
    invoice_scope: bool,
) -> None:
    payload: dict[str, object] = {"question": question}
    if invoice_scope:
        payload["document_id"] = str(workspace.document_id)
    response = workspace.client.post("/v1/workspace/questions", json=payload)
    assert response.status_code == 200, response.text
    assert response.json()["supported"] is True
    if question == "Who is the vendor?":
        assert response.json()["citations"][0]["value"] == "Harbor Supply"


@pytest.mark.parametrize(
    "path",
    [
        "/v1/categories",
        "/v1/organization/collaborators",
        "/v1/workspace/summary",
        f"/v1/documents/{uuid.uuid4()}/workspace",
    ],
)
def test_workflow_routes_require_authentication(path: str) -> None:
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        assert client.get(path).status_code == 401


@pytest.mark.skipif("DATABASE_OWNER_URL" not in os.environ, reason="Postgres integration test")
def test_workflow_tables_enforce_tenant_rls_and_append_only_history() -> None:
    owner_engine = create_engine(normalize_database_url(os.environ["DATABASE_OWNER_URL"]))
    app_engine = create_engine(normalize_database_url(os.environ["DATABASE_URL"]))
    try:
        with Session(owner_engine) as owner:
            organizations = owner.scalars(select(Organization).limit(2)).all()
            assert len(organizations) == 2
            first, second = organizations
            org_id, other_org_id = first.id, second.id
        with Session(app_engine) as session:
            set_org_context(session, org_id)
            category = InvoiceCategory(org_id=org_id, name="RLS test", name_key=uuid.uuid4().hex)
            session.add(category)
            session.flush()
            assert all(row.org_id == org_id for row in session.scalars(select(InvoiceCategory)))
            assert (
                session.scalar(
                    select(InvoiceCategory).where(
                        InvoiceCategory.org_id == other_org_id,
                    )
                )
                is None
            )
            session.add(
                InvoiceCategory(org_id=other_org_id, name="Forbidden", name_key=uuid.uuid4().hex)
            )
            with pytest.raises(DBAPIError):
                session.flush()
            session.rollback()
            from sqlalchemy import text

            # Permissions reject mutation even when no row matches the predicate.
            for table in ("invoice_comments", "invoice_reviews"):
                set_org_context(session, org_id)
                with pytest.raises(DBAPIError):
                    session.execute(
                        text(f"DELETE FROM {table} WHERE org_id = :org"), {"org": org_id}
                    )
                session.rollback()
    finally:
        owner_engine.dispose()
        app_engine.dispose()


@pytest.mark.skipif("DATABASE_OWNER_URL" not in os.environ, reason="Postgres integration test")
def test_http_restricted_invoice_acl_pdf_retry_duplicate_and_grant_revocation() -> None:
    """Use real authentication, RLS and HTTP handlers across every document entry point."""
    import hashlib
    from pathlib import Path

    from sqlalchemy import delete

    from app.main import app
    from app.models import OutboxEvent, WorkflowConfig
    from app.security import make_session_token
    from app.storage import get_store
    from app.workflow_models import InvoiceGrant

    class MemoryStore:
        def __init__(self) -> None:
            self.objects: dict[str, bytes] = {}

        def put(self, key: str, data: bytes) -> None:
            self.objects[key] = data

        def get(self, key: str) -> bytes:
            return self.objects[key]

    owner_engine = create_engine(normalize_database_url(os.environ["DATABASE_OWNER_URL"]))
    org_id, outside_id = uuid.uuid4(), uuid.uuid4()
    actor_ids = {name: uuid.uuid4() for name in ("admin", "member", "reviewer", "external")}
    invoice = (Path(__file__).parents[3] / "examples" / "northwind-invoice.pdf").read_bytes()
    store = MemoryStore()
    document_id = uuid.uuid4()
    storage_key = f"{org_id}/{document_id}.pdf"
    store.put(storage_key, invoice)
    try:
        with Session(owner_engine) as session:
            session.add_all(
                [
                    Organization(id=org_id, slug=f"acl-{org_id.hex}", name="Private invoices"),
                    Organization(id=outside_id, slug=f"acl-{outside_id.hex}", name="Other company"),
                ]
            )
            for name, user_id in actor_ids.items():
                session.add(
                    User(
                        id=user_id,
                        email=f"{name}-{user_id.hex}@example.com",
                        password_hash="unused-token-test",
                    )
                )
            session.flush()
            for name, user_id in actor_ids.items():
                session.add(
                    Membership(
                        org_id=outside_id if name == "external" else org_id,
                        user_id=user_id,
                        role="member" if name == "external" else name,
                        status="active",
                    )
                )
            session.add(WorkflowConfig(org_id=org_id, version=1, config_json="{}"))
            session.flush()
            session.add(
                Document(
                    id=document_id,
                    org_id=org_id,
                    uploaded_by=actor_ids["member"],
                    filename="private-financial-data.pdf",
                    content_type="application/pdf",
                    size_bytes=len(invoice),
                    content_hash=hashlib.sha256(invoice).hexdigest(),
                    storage_key=storage_key,
                    workflow_config_version=1,
                    status="failed",
                    failure_reason="Test extraction failure",
                )
            )
            session.commit()
        app.dependency_overrides[get_store] = lambda: store
        path = f"/v1/documents/{document_id}"
        with TestClient(app) as client:

            def login(actor: str) -> None:
                client.cookies.clear()
                client.cookies.set(
                    "opspilot_session",
                    make_session_token(
                        actor_ids[actor],
                        outside_id if actor == "external" else org_id,
                    ),
                )

            login("admin")
            first_share = client.post(
                f"{path}/sharing",
                json={
                    "version": 0,
                    "visibility": "restricted",
                    "user_ids": [],
                },
            )
            assert first_share.status_code == 200, first_share.text
            for actor in ("reviewer", "external"):
                login(actor)
                assert client.get("/v1/documents").json() == []
                for suffix in ("", "/file", "/workspace"):
                    assert client.get(path + suffix).status_code == 404
                assert client.post(f"{path}/retry").status_code == 404
                assert client.post(f"{path}/comments", json={"body": "Blocked"}).status_code == 404
                assert (
                    client.post(
                        "/v1/workspace/questions",
                        json={
                            "question": "What is the total?",
                            "document_id": str(document_id),
                        },
                    ).status_code
                    == 404
                )
                assert client.get("/v1/workspace/summary").json()["total_documents"] == 0
            login("reviewer")
            denied_duplicate = client.post(
                "/v1/documents",
                files={
                    "file": ("guess.pdf", invoice, "application/pdf"),
                },
            )
            assert denied_duplicate.status_code == 409, denied_duplicate.text
            assert str(document_id) not in denied_duplicate.text
            assert "private-financial-data.pdf" not in denied_duplicate.text
            login("member")
            pdf = client.get(f"{path}/file")
            assert pdf.status_code == 200 and pdf.content == invoice
            assert pdf.headers["content-type"] == "application/pdf"
            assert "no-store" in pdf.headers["cache-control"]
            assert (
                client.get(f"{path}/file?download=true")
                .headers["content-disposition"]
                .startswith("attachment;")
            )
            login("admin")
            granted = client.post(
                f"{path}/sharing",
                json={
                    "version": 1,
                    "visibility": "restricted",
                    "user_ids": [str(actor_ids["reviewer"])],
                },
            )
            assert granted.status_code == 200, granted.text
            login("reviewer")
            assert client.get("/v1/documents").json()[0]["id"] == str(document_id)
            assert client.get(path).status_code == 200
            assert client.get(f"{path}/file").content == invoice
            assert client.get("/v1/workspace/summary").json()["total_documents"] == 1
            duplicate = client.post(
                "/v1/documents",
                files={
                    "file": ("permitted-copy.pdf", invoice, "application/pdf"),
                },
            )
            assert duplicate.status_code == 202 and duplicate.json()["duplicate"] is True
            comment = client.post(f"{path}/comments", json={"body": "Please retry the extraction"})
            assert comment.status_code == 201, comment.text
            retry = client.post(f"{path}/retry")
            assert retry.status_code == 202, retry.text
            login("admin")
            revoked = client.post(
                f"{path}/sharing",
                json={
                    "version": 2,
                    "visibility": "restricted",
                    "user_ids": [],
                },
            )
            assert revoked.status_code == 200, revoked.text
            login("reviewer")
            assert client.get(f"{path}/workspace").status_code == 404
            assert client.get(f"{path}/file").status_code == 404
            assert client.get("/v1/documents").json() == []
            assert client.get("/v1/workspace/summary").json()["total_documents"] == 0
            # Concurrent decisions use separate real app transactions. Exactly one wins.
            with Session(owner_engine) as session:
                document = session.get(Document, document_id)
                assert document is not None
                document.status = "needs_review"
                session.execute(delete(OutboxEvent).where(OutboxEvent.document_id == document_id))
                session.commit()
            login("admin")
            verified = client.post(
                f"{path}/metadata",
                json={
                    "version": 3,
                    "verified_amount": "123.45",
                    "currency": "USD",
                },
            )
            assert verified.status_code == 200, verified.text
            from concurrent.futures import ThreadPoolExecutor
            from threading import Barrier

            barrier = Barrier(2)

            def concurrent_approval() -> int:
                with TestClient(app) as concurrent_client:
                    concurrent_client.cookies.set(
                        "opspilot_session",
                        make_session_token(
                            actor_ids["admin"],
                            org_id,
                        ),
                    )
                    barrier.wait(timeout=5)
                    decision = concurrent_client.post(
                        f"{path}/review",
                        json={
                            "version": 4,
                            "decision": "approve",
                        },
                    )
                    return int(decision.status_code)

            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(concurrent_approval) for _ in range(2)]
                assert sorted(future.result(timeout=10) for future in futures) == [200, 409]
            final_workspace = client.get(f"{path}/workspace").json()
            assert final_workspace["version"] == 5
            assert len(final_workspace["reviews"]) == 1
    finally:
        app.dependency_overrides.pop(get_store, None)
        with Session(owner_engine) as session:
            for model in (
                InvoiceReview,
                InvoiceGrant,
                InvoiceComment,
                InvoiceMetadata,
                InvoiceCategory,
                ExtractedField,
                ExtractionRun,
                OutboxEvent,
                AuditEvent,
                Document,
                WorkflowConfig,
                Membership,
            ):
                session.execute(delete(model).where(model.org_id.in_([org_id, outside_id])))
            session.execute(delete(Organization).where(Organization.id.in_([org_id, outside_id])))
            session.execute(delete(User).where(User.id.in_(actor_ids.values())))
            session.commit()
        owner_engine.dispose()
