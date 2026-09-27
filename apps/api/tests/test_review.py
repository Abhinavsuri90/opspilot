"""Review queue, field corrections, approval gates, timeline and list filters over SQLite."""

import json
import time
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, event, select, update
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.auth import current_session
from app.main import app
from app.models import (
    AuditEvent,
    Base,
    Document,
    ExtractedField,
    ExtractionRun,
    Membership,
    Organization,
    User,
    WorkflowConfig,
)
from app.storage import StorageError, get_store
from app.workflow_config import default_invoice_config
from app.workflow_models import FieldCorrection, InvoiceComment, InvoiceMetadata, ReviewTask

NOW = datetime.now(UTC).replace(microsecond=0)


class FailingStore:
    def __init__(self, data: bytes | None = None) -> None:
        self.data = data

    def put(self, key: str, data: bytes) -> None:
        raise StorageError("Object storage is unavailable")

    def get(self, key: str) -> bytes:
        if self.data is None:
            raise StorageError("Object storage is unavailable")
        return self.data


@dataclass
class Review:
    client: TestClient
    engine: Engine
    actors: dict[str, uuid.UUID]
    org_id: uuid.UUID
    other_org_id: uuid.UUID
    flagged_id: uuid.UUID
    clean_id: uuid.UUID
    approved_id: uuid.UUID
    other_id: uuid.UUID
    other_field_id: uuid.UUID
    actor: str = "admin"

    def detail(self, document_id: uuid.UUID | None = None) -> dict[str, Any]:
        response = self.client.get(f"/v1/documents/{document_id or self.flagged_id}")
        assert response.status_code == 200, response.text
        return dict(response.json())

    def field_id(self, name: str, document_id: uuid.UUID | None = None) -> str:
        return str(next(f["id"] for f in self.detail(document_id)["fields"] if f["name"] == name))

    def correct(
        self,
        name: str,
        action: str,
        value: str | None = None,
        *,
        document_id: uuid.UUID | None = None,
        version: int | None = None,
    ) -> Any:
        document_id = document_id or self.flagged_id
        payload: dict[str, object] = {
            "version": self.detail(document_id)["version"] if version is None else version,
            "action": action,
        }
        if value is not None:
            payload["value"] = value
        return self.client.post(
            f"/v1/documents/{document_id}/fields/{self.field_id(name, document_id)}", json=payload
        )

    def review(self, decision: str, document_id: uuid.UUID | None = None, **extra: object) -> Any:
        document_id = document_id or self.flagged_id
        version = self.client.get(f"/v1/documents/{document_id}/workspace").json()["version"]
        return self.client.post(
            f"/v1/documents/{document_id}/review",
            json={"version": version, "decision": decision, **extra},
        )


def make_document(
    org_id: uuid.UUID, user_id: uuid.UUID, filename: str, status: str, created_at: datetime
) -> Document:
    identity = uuid.uuid4()
    return Document(
        id=identity,
        org_id=org_id,
        uploaded_by=user_id,
        filename=filename,
        content_type="application/pdf",
        size_bytes=100,
        content_hash=identity.hex,
        storage_key=f"{org_id}/{identity}.pdf",
        workflow_config_version=1,
        status=status,
        created_at=created_at,
        updated_at=created_at,
    )


def add_fields(
    session: Session,
    org_id: uuid.UUID,
    document: Document,
    rows: list[dict[str, Any]],
    created_at: datetime,
) -> list[ExtractedField]:
    run = ExtractionRun(
        org_id=org_id,
        document_id=document.id,
        provider="mock",
        model="invoice-pattern-v2",
        prompt_version="mock-v2",
        raw_json=json.dumps({"fields": rows, "tokens_in": None, "latency_ms": 3}),
        created_at=created_at,
    )
    session.add(run)
    session.flush()
    fields = []
    for row in rows:
        field = ExtractedField(
            org_id=org_id,
            document_id=document.id,
            extraction_run_id=run.id,
            name=row["name"],
            value=row["value"],
            evidence=row.get("evidence", f"{row['name']}: {row['value']}"),
            page_number=1,
            field_type=row.get("field_type", "text"),
            required=row.get("required", False),
            confidence=Decimal(str(row.get("confidence", "1.0"))),
            threshold=Decimal(str(row.get("threshold", "0.8"))),
            status=row.get("status", "auto"),
            signals_json=json.dumps(row.get("signals", {"grounding": 1.0, "format": 1.0})),
            reasons_json=json.dumps(row.get("reasons", [])),
        )
        session.add(field)
        fields.append(field)
    session.flush()
    return fields


@pytest.fixture
def review() -> Iterator[Review]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )

    @event.listens_for(engine, "connect")
    def foreign_keys(connection: object, _: object) -> None:
        from sqlite3 import Connection

        assert isinstance(connection, Connection)
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    org_id, other_org = uuid.uuid4(), uuid.uuid4()
    names = ("admin", "reviewer", "reviewer2", "member", "viewer", "external")
    actors = {name: uuid.uuid4() for name in names}
    with Session(engine) as session:
        session.add_all(
            [
                Organization(id=org_id, slug="review", name="Review", default_currency="USD"),
                Organization(id=other_org, slug="outside", name="Outside"),
            ]
        )
        for name, user_id in actors.items():
            session.add(User(id=user_id, email=f"{name}@example.com", password_hash="unused"))
        session.flush()
        roles = {"reviewer2": "reviewer", "external": "admin"}
        for name, user_id in actors.items():
            session.add(
                Membership(
                    org_id=other_org if name == "external" else org_id,
                    user_id=user_id,
                    role=roles.get(name, name),
                    status="active",
                )
            )
        for target in (org_id, other_org):
            session.add(
                WorkflowConfig(
                    org_id=target, version=1, config_json=default_invoice_config().model_dump_json()
                )
            )
        session.flush()

        flagged = make_document(
            org_id, actors["member"], "harbor-supply.pdf", "needs_review", NOW - timedelta(hours=5)
        )
        clean = make_document(
            org_id, actors["member"], "maple-office.pdf", "needs_review", NOW - timedelta(hours=1)
        )
        approved = make_document(
            org_id, actors["admin"], "approved.pdf", "approved", NOW - timedelta(minutes=30)
        )
        other = make_document(
            other_org, actors["external"], "outside.pdf", "needs_review", NOW - timedelta(hours=2)
        )
        session.add_all([flagged, clean, approved, other])
        session.flush()
        add_fields(
            session,
            org_id,
            flagged,
            [
                {"name": "vendor", "value": "Harbor Supply", "required": True},
                {
                    "name": "invoice_number",
                    "value": "HS-1001",
                    "field_type": "identifier",
                    "required": True,
                },
                {
                    "name": "invoice_date",
                    "value": "2026-13-45",
                    "field_type": "date",
                    "required": True,
                    "confidence": "0.6154",
                    "status": "needs_review",
                    "signals": {"grounding": 1.0, "format": 0.0, "self_report": 1.0},
                    "reasons": ["Value is not a valid date"],
                },
                {
                    "name": "total",
                    "value": "$19.25",
                    "field_type": "money",
                    "required": True,
                    "confidence": "0.85",
                    "threshold": "0.9",
                    "status": "needs_review",
                    "reasons": ["Confidence 0.85 is below the 0.90 threshold"],
                },
            ],
            NOW - timedelta(hours=5, minutes=-1),
        )
        add_fields(
            session,
            org_id,
            clean,
            [
                {"name": "vendor", "value": "Maple Office"},
                {"name": "invoice_number", "value": "MO-2002", "field_type": "identifier"},
                {"name": "invoice_date", "value": "2026-09-10", "field_type": "date"},
                {"name": "total", "value": "$40.00", "field_type": "money"},
                {"name": "currency", "value": "EUR", "field_type": "currency"},
            ],
            NOW - timedelta(minutes=59),
        )
        other_fields = add_fields(
            session,
            other_org,
            other,
            [{"name": "total", "value": "$1.00", "field_type": "money"}],
            NOW - timedelta(hours=2),
        )
        session.add_all(
            [
                ReviewTask(
                    document_id=flagged.id,
                    org_id=org_id,
                    opened_at=NOW - timedelta(hours=5),
                    sla_minutes=240,
                    due_at=NOW - timedelta(hours=1),
                ),
                ReviewTask(
                    document_id=clean.id,
                    org_id=org_id,
                    opened_at=NOW - timedelta(hours=1),
                    sla_minutes=240,
                    due_at=NOW + timedelta(hours=3),
                ),
                InvoiceMetadata(
                    document_id=clean.id,
                    org_id=org_id,
                    assigned_reviewer_id=actors["reviewer"],
                    version=0,
                ),
                InvoiceComment(
                    org_id=org_id,
                    document_id=flagged.id,
                    author_user_id=actors["member"],
                    body="Please check the date",
                    created_at=NOW - timedelta(hours=4),
                ),
            ]
        )
        for offset, event_type in enumerate(
            ("document.received", "document.queued", "document.extracting", "document.needs_review")
        ):
            session.add(
                AuditEvent(
                    org_id=org_id,
                    actor_user_id=actors["member"] if offset < 2 else None,
                    document_id=flagged.id,
                    event_type=event_type,
                    detail_json=json.dumps({"document_id": str(flagged.id)}),
                    created_at=NOW - timedelta(hours=5) + timedelta(seconds=offset),
                )
            )
        session.commit()
        ids = (flagged.id, clean.id, approved.id, other.id, other_fields[0].id)

    with TestClient(app) as client:
        state = Review(client, engine, actors, org_id, other_org, *ids)

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
        app.dependency_overrides[get_store] = lambda: FailingStore()
        try:
            yield state
        finally:
            app.dependency_overrides.pop(current_session, None)
            app.dependency_overrides.pop(get_store, None)
    engine.dispose()


def test_document_detail_exposes_confidence_flags_and_sla(review: Review) -> None:
    body = review.detail()
    assert body["document_type"] == "invoice"
    assert body["version"] == 0 and body["provider"] == "mock"
    assert body["flagged_count"] == 2
    fields = {field["name"]: field for field in body["fields"]}
    assert fields["invoice_date"]["status"] == "needs_review"
    assert fields["invoice_date"]["label"] == "Invoice Date"
    assert fields["invoice_date"]["field_type"] == "date" and fields["invoice_date"]["required"]
    assert fields["invoice_date"]["confidence"] == 0.6154
    assert fields["invoice_date"]["threshold"] == 0.8
    assert fields["invoice_date"]["signals"] == {
        "grounding": 1.0,
        "format": 0.0,
        "self_report": 1.0,
    }
    assert fields["invoice_date"]["reasons"] == ["Value is not a valid date"]
    assert fields["invoice_date"]["current_value"] == fields["invoice_date"]["value"]
    assert fields["invoice_date"]["corrected_by_email"] is None
    assert fields["vendor"]["status"] == "auto"
    assert body["review_task"]["overdue"] is True
    assert body["review_task"]["sla_minutes"] == 240
    assert body["review_task"]["outcome"] is None
    assert [rule["name"] for rule in body["rule_results"]] == ["totals_add_up", "due_after_issue"]
    assert all(rule["passed"] is None for rule in body["rule_results"])
    assert review.detail(review.approved_id)["review_task"] is None


def test_edit_and_accept_record_corrections_and_bump_version(review: Review) -> None:
    review.actor = "reviewer"
    edited = review.correct("invoice_date", "edit", "2026-09-05")
    assert edited.status_code == 200, edited.text
    body = edited.json()
    assert body["version"] == 1 and body["flagged_count"] == 1
    date_field = next(field for field in body["fields"] if field["name"] == "invoice_date")
    assert date_field["status"] == "corrected"
    assert date_field["value"] == "2026-13-45"
    assert date_field["current_value"] == "2026-09-05"
    assert date_field["corrected_by_email"] == "reviewer@example.com"
    accepted = review.correct("total", "accept")
    assert accepted.status_code == 200, accepted.text
    body = accepted.json()
    assert body["version"] == 2 and body["flagged_count"] == 0
    total = next(field for field in body["fields"] if field["name"] == "total")
    assert total["status"] == "approved" and total["current_value"] == "$19.25"
    # A second edit of the same field keeps the original evidence immutable.
    again = review.correct("invoice_date", "edit", "06-Sep-26")
    assert again.status_code == 200
    with Session(review.engine) as session:
        corrections = session.scalars(
            select(FieldCorrection)
            .where(FieldCorrection.document_id == review.flagged_id)
            .order_by(FieldCorrection.created_at, FieldCorrection.id)
        ).all()
        assert [(row.kind, row.before_value, row.after_value) for row in corrections] == [
            ("edit", "2026-13-45", "2026-09-05"),
            ("accept", "$19.25", "$19.25"),
            ("edit", "2026-09-05", "06-Sep-26"),
        ]
        assert all(row.reviewer_user_id == review.actors["reviewer"] for row in corrections)
        original = session.scalar(
            select(ExtractedField).where(
                ExtractedField.document_id == review.flagged_id,
                ExtractedField.name == "invoice_date",
            )
        )
        assert original is not None and original.value == "2026-13-45"
        audits = session.scalars(
            select(AuditEvent)
            .where(
                AuditEvent.document_id == review.flagged_id,
                AuditEvent.event_type.in_(["invoice.field_edited", "invoice.field_accepted"]),
            )
            .order_by(AuditEvent.created_at, AuditEvent.id)
        ).all()
        assert [row.event_type for row in audits] == [
            "invoice.field_edited",
            "invoice.field_accepted",
            "invoice.field_edited",
        ]
        assert json.loads(audits[0].detail_json) == {
            "document_id": str(review.flagged_id),
            "field": "invoice_date",
            "before": "2026-13-45",
            "after": "2026-09-05",
        }
        assert [row.document_id for row in audits] == [review.flagged_id] * 3
    assert review.detail(review.flagged_id)["version"] == 3


def test_invalid_edits_return_reasons(review: Review) -> None:
    bad_date = review.correct("invoice_date", "edit", "not a date")
    assert bad_date.status_code == 422
    assert bad_date.json()["error"]["message"] == "Value is not a valid date"
    bad_money = review.correct("total", "edit", "nineteen")
    assert bad_money.status_code == 422
    assert bad_money.json()["error"]["message"] == "Value is not a valid amount"
    bad_id = review.correct("invoice_number", "edit", "!!")
    assert bad_id.status_code == 422
    assert "expected pattern" in bad_id.json()["error"]["message"]
    assert review.correct("total", "accept", "$1").status_code == 422
    assert review.correct("total", "edit").status_code == 422
    assert review.correct("total", "edit", "   ").status_code == 422
    assert review.detail()["version"] == 0


def test_correction_permissions_conflicts_and_lookups(review: Review) -> None:
    stale = review.correct("total", "accept", version=7)
    assert stale.status_code == 409
    for actor in ("member", "viewer"):
        review.actor = actor
        assert review.correct("total", "accept").status_code == 403
    review.actor = "reviewer2"
    # reviewer2 is not the assigned reviewer of the clean document.
    assert review.correct("total", "accept", document_id=review.clean_id).status_code == 403
    review.actor = "external"
    assert review.client.get(f"/v1/documents/{review.flagged_id}").status_code == 404
    assert (
        review.client.post(
            f"/v1/documents/{review.flagged_id}/fields/{uuid.uuid4()}",
            json={"version": 0, "action": "accept"},
        ).status_code
        == 404
    )
    review.actor = "admin"
    unknown = review.client.post(
        f"/v1/documents/{review.flagged_id}/fields/{uuid.uuid4()}",
        json={"version": 0, "action": "accept"},
    )
    assert unknown.status_code == 404
    # A real field id that belongs to another document (and tenant) is not reachable here.
    cross_document = review.client.post(
        f"/v1/documents/{review.flagged_id}/fields/{review.other_field_id}",
        json={"version": 0, "action": "accept"},
    )
    assert cross_document.status_code == 404
    with Session(review.engine) as session:
        assert session.scalars(select(FieldCorrection)).all() == []
    completed = review.client.post(
        f"/v1/documents/{review.approved_id}/fields/{uuid.uuid4()}",
        json={"version": 0, "action": "accept"},
    )
    assert completed.status_code == 409
    assert review.client.post(
        f"/v1/documents/{review.flagged_id}/fields/not-a-uuid",
        json={"version": 0, "action": "accept"},
    ).status_code == 422


def test_approval_waits_for_flagged_fields_then_derives_verified_money(review: Review) -> None:
    blocked = review.review("approve")
    assert blocked.status_code == 422
    assert blocked.json()["error"]["message"] == "2 field(s) still need review"
    assert review.correct("invoice_date", "edit", "2026-09-05").status_code == 200
    still_blocked = review.review("approve")
    assert still_blocked.status_code == 422
    assert still_blocked.json()["error"]["message"] == "1 field(s) still need review"
    assert review.correct("total", "edit", "$21.75").status_code == 200
    approved = review.review("approve")
    assert approved.status_code == 200, approved.text
    workspace = approved.json()
    assert Decimal(str(workspace["verified_amount"])) == Decimal("21.75")
    assert workspace["currency"] == "USD"
    assert workspace["capabilities"]["can_review"] is True
    body = review.detail()
    assert body["status"] == "approved"
    assert body["review_task"]["outcome"] == "approved"
    assert body["review_task"]["completed_at"] is not None
    assert body["review_task"]["overdue"] is False
    reopened = review.review("reopen")
    assert reopened.status_code == 200, reopened.text
    body = review.detail()
    assert body["status"] == "needs_review"
    assert body["review_task"]["outcome"] is None
    assert body["review_task"]["completed_at"] is None
    assert body["review_task"]["overdue"] is False
    rejected = review.review("reject", comment="Duplicate")
    assert rejected.status_code == 200
    assert review.detail()["review_task"]["outcome"] == "rejected"


def test_approval_uses_effective_currency_field_or_fails_when_underivable(
    review: Review,
) -> None:
    review.actor = "reviewer"
    approved = review.review("approve", document_id=review.clean_id)
    assert approved.status_code == 200, approved.text
    assert Decimal(str(approved.json()["verified_amount"])) == Decimal("40")
    assert approved.json()["currency"] == "EUR"
    review.actor = "admin"
    assert review.review("reopen", document_id=review.clean_id).status_code == 200
    with Session(review.engine) as session, session.begin():
        session.execute(
            update(ExtractedField)
            .where(ExtractedField.document_id == review.clean_id, ExtractedField.name == "total")
            .values(value="forty")
        )
        session.execute(
            update(InvoiceMetadata)
            .where(InvoiceMetadata.document_id == review.clean_id)
            .values(verified_amount=None, currency=None)
        )
    failed = review.review("approve", document_id=review.clean_id)
    assert failed.status_code == 422
    assert failed.json()["error"]["message"] == (
        "Verify the invoice amount and currency before approval"
    )


def test_review_queue_filters_and_ordering(review: Review) -> None:
    client = review.client
    queue = client.get("/v1/review/queue").json()
    assert [row["document_id"] for row in queue] == [str(review.flagged_id), str(review.clean_id)]
    first, second = queue
    assert first == {
        "document_id": str(review.flagged_id),
        "filename": "harbor-supply.pdf",
        "document_type": "invoice",
        "vendor": "Harbor Supply",
        "total": "$19.25",
        "currency": None,
        "flagged_count": 2,
        "opened_at": first["opened_at"],
        "due_at": first["due_at"],
        "overdue": True,
        "assigned_reviewer_id": None,
        "assigned_reviewer_email": None,
        "created_at": first["created_at"],
    }
    assert second["vendor"] == "Maple Office" and second["currency"] == "EUR"
    assert second["overdue"] is False and second["flagged_count"] == 0
    assert second["assigned_reviewer_email"] == "reviewer@example.com"
    assert second["assigned_reviewer_id"] == str(review.actors["reviewer"])

    def ids(**params: object) -> list[str]:
        response = client.get("/v1/review/queue", params=params)
        assert response.status_code == 200, response.text
        return [row["document_id"] for row in response.json()]

    assert ids(vendor="maple") == [str(review.clean_id)]
    assert ids(vendor="MAPLE OFF") == [str(review.clean_id)]
    assert ids(vendor="%") == []
    assert ids(assigned="unassigned") == [str(review.flagged_id)]
    assert ids(document_type="receipt") == []
    assert ids(max_age_hours=2) == [str(review.clean_id)]
    assert ids(offset=1, limit=1) == [str(review.clean_id)]
    assert client.get("/v1/review/queue", params={"assigned": "someone"}).status_code == 422
    assert client.get("/v1/review/queue", params={"limit": 0}).status_code == 422
    review.actor = "reviewer"
    assert ids(assigned="me") == [str(review.clean_id)]
    review.actor = "reviewer2"
    assert ids(assigned="me") == []
    review.actor = "admin"
    assert review.correct("vendor", "edit", "Harbour Supplies Ltd").status_code == 200
    assert ids(vendor="harbour") == [str(review.flagged_id)]
    assert ids(vendor="Harbor Supply") == []
    assert client.get("/v1/review/queue").json()[0]["vendor"] == "Harbour Supplies Ltd"
    review.actor = "external"
    # The other tenant's admin only sees the other tenant's queue.
    assert ids() == [str(review.other_id)]
    assert ids(vendor="harbour") == []


def test_timeline_merges_sources_chronologically(review: Review) -> None:
    review.actor = "reviewer"
    assert review.correct("invoice_date", "edit", "2026-09-05").status_code == 200
    assert review.correct("total", "accept").status_code == 200
    assert review.review("approve").status_code == 200
    response = review.client.get(f"/v1/documents/{review.flagged_id}/timeline")
    assert response.status_code == 200, response.text
    timeline = response.json()
    assert [(entry["kind"], entry["event_type"]) for entry in timeline] == [
        ("audit", "document.received"),
        ("audit", "document.queued"),
        ("audit", "document.extracting"),
        ("audit", "document.needs_review"),
        ("extraction", "extraction.completed"),
        ("comment", "comment.added"),
        ("correction", "field.edit"),
        ("correction", "field.accept"),
        ("review", "review.approve"),
    ]
    stamps = [entry["at"] for entry in timeline]
    assert stamps == sorted(stamps)
    assert timeline[0]["actor_email"] == "member@example.com"
    assert timeline[0]["summary"] == "Document: received"
    assert timeline[2]["actor_email"] is None
    assert timeline[4]["summary"] == "Extracted 4 field(s) with mock"
    assert timeline[4]["detail"]["latency_ms"] == 3
    assert timeline[5]["detail"]["body"] == "Please check the date"
    assert timeline[6] == {
        "at": timeline[6]["at"],
        "kind": "correction",
        "event_type": "field.edit",
        "actor_email": "reviewer@example.com",
        "summary": "Edited invoice date",
        "detail": {"field": "invoice_date", "before": "2026-13-45", "after": "2026-09-05"},
    }
    assert timeline[8]["detail"] == {"decision": "approve", "comment": ""}
    review.actor = "external"
    assert review.client.get(f"/v1/documents/{review.flagged_id}/timeline").status_code == 404
    review.actor = "admin"
    assert review.client.get(f"/v1/documents/{review.other_id}/timeline").status_code == 404


def test_document_list_filters_and_summary_fields(review: Review) -> None:
    client = review.client

    def listing(**params: object) -> list[dict[str, Any]]:
        response = client.get("/v1/documents", params=params)
        assert response.status_code == 200, response.text
        return list(response.json())

    everything = listing()
    assert [row["filename"] for row in everything] == [
        "approved.pdf",
        "maple-office.pdf",
        "harbor-supply.pdf",
    ]
    by_name = {row["filename"]: row for row in everything}
    assert by_name["harbor-supply.pdf"]["flagged_count"] == 2
    assert by_name["maple-office.pdf"]["flagged_count"] == 0
    assert all(row["document_type"] == "invoice" for row in everything)
    assert [row["id"] for row in listing(status="needs_review")] == [
        str(review.clean_id),
        str(review.flagged_id),
    ]
    assert [row["id"] for row in listing(status="in_progress")] == []
    assert [row["id"] for row in listing(status="approved")] == [str(review.approved_id)]
    assert listing(status="auto_approved") == []
    assert client.get("/v1/documents", params={"status": "bogus"}).status_code == 422
    assert [row["id"] for row in listing(q="HARBOR")] == [str(review.flagged_id)]
    assert listing(q="%") == []
    assert [row["id"] for row in listing(offset=1, limit=1)] == [str(review.clean_id)]
    assert client.get("/v1/documents", params={"limit": 101}).status_code == 422
    category = client.post("/v1/categories", json={"name": "Office"}).json()
    assert listing(category_id=category["id"]) == []
    categorized = client.post(
        f"/v1/documents/{review.clean_id}/metadata",
        json={"version": 0, "category_id": category["id"]},
    )
    assert categorized.status_code == 200, categorized.text
    assert [row["id"] for row in listing(category_id=category["id"])] == [str(review.clean_id)]
    assert client.get("/v1/documents", params={"category_id": "nope"}).status_code == 422
    review.actor = "external"
    assert [row["filename"] for row in listing()] == ["outside.pdf"]


def test_upload_rejects_pdf_that_takes_too_long_to_parse(
    review: Review, monkeypatch: pytest.MonkeyPatch
) -> None:
    def slow_pages(data: bytes) -> list[str]:
        time.sleep(1.5)
        return ["never used"]

    monkeypatch.setattr("app.document_service.pdf_pages", slow_pages)
    monkeypatch.setattr(
        "app.document_service.get_settings",
        lambda: SimpleNamespace(max_documents_per_org=100, upload_parse_timeout_seconds=0.2),
    )
    started = time.monotonic()
    response = review.client.post(
        "/v1/documents",
        files={"file": ("slow.pdf", b"%PDF-1.4 " + uuid.uuid4().bytes, "application/pdf")},
    )
    assert time.monotonic() - started < 1.2
    assert response.status_code == 400
    assert response.json()["error"]["message"] == "PDF took too long to parse"


def test_file_download_reports_storage_and_integrity_failures(review: Review) -> None:
    unavailable = review.client.get(f"/v1/documents/{review.flagged_id}/file")
    assert unavailable.status_code == 503
    assert unavailable.json()["error"]["message"] == "Document storage is unavailable"
    app.dependency_overrides[get_store] = lambda: FailingStore(b"%PDF-1.4 wrong bytes")
    corrupted = review.client.get(f"/v1/documents/{review.flagged_id}/file")
    assert corrupted.status_code == 503
    assert corrupted.json()["error"]["message"] == "Stored document failed integrity check"
    review.actor = "external"
    assert review.client.get(f"/v1/documents/{review.flagged_id}/file").status_code == 404
