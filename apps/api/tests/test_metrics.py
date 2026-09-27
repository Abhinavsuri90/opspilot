"""KPI overview and the actions summary, computed over the documents a caller may see."""

import json
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.action_models import Action
from app.auth import current_session
from app.main import app
from app.models import Base, Document, Membership, Organization, User, WorkflowConfig
from app.workflow_config import default_invoice_config
from app.workflow_models import FieldCorrection, InvoiceMetadata, ReviewTask
from tests.test_review import add_fields, make_document

NOW = datetime.now(UTC).replace(microsecond=0)
TODAY = NOW.date()


def at_day(days_ago: int, hour: int = 10) -> datetime:
    return datetime.combine(
        TODAY - timedelta(days=days_ago), datetime.min.time(), tzinfo=UTC
    ).replace(hour=hour)


@dataclass
class Metrics:
    client: TestClient
    engine: Engine
    actors: dict[str, uuid.UUID]
    org_id: uuid.UUID
    actor: str = "admin"

    def overview(self, **params: object) -> dict[str, Any]:
        response = self.client.get("/v1/metrics/overview", params=params)
        assert response.status_code == 200, response.text
        return dict(response.json())


def _fields(
    session: Session, org_id: uuid.UUID, document: Document, count: int, when: datetime
) -> list[uuid.UUID]:
    rows = [{"name": f"field_{index}", "value": str(index)} for index in range(count)]
    return [field.id for field in add_fields(session, org_id, document, rows, when)]


@pytest.fixture
def metrics() -> Iterator[Metrics]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    org_id, other_org = uuid.uuid4(), uuid.uuid4()
    actors = {name: uuid.uuid4() for name in ("admin", "member", "external")}
    with Session(engine) as session:
        session.add_all(
            [
                Organization(id=org_id, slug="kpi", name="KPI"),
                Organization(id=other_org, slug="elsewhere", name="Elsewhere"),
            ]
        )
        for name, user_id in actors.items():
            session.add(User(id=user_id, email=f"{name}@example.com", password_hash="unused"))
        session.flush()
        for name, user_id in actors.items():
            session.add(
                Membership(
                    org_id=other_org if name == "external" else org_id,
                    user_id=user_id,
                    role="admin" if name == "external" else name,
                    status="active",
                )
            )
        config = default_invoice_config().model_copy(update={"baseline_minutes": 12})
        for target in (org_id, other_org):
            session.add(
                WorkflowConfig(org_id=target, version=1, config_json=config.model_dump_json())
            )
        session.flush()
        member = actors["member"]

        def document(
            name: str,
            status: str,
            days_ago: int,
            *,
            fields: int,
            task: tuple[int | None, str | None] | None = None,
            document_type: str = "invoice",
            restricted: bool = False,
            org: uuid.UUID = org_id,
            owner: uuid.UUID = member,
        ) -> Document:
            created = at_day(days_ago)
            row = make_document(org, owner, name, status, created)
            row.document_type = document_type
            session.add(row)
            session.flush()
            ids = (
                _fields(session, org, row, fields, created + timedelta(minutes=1)) if fields else []
            )
            if task is not None:
                minutes, outcome = task
                session.add(
                    ReviewTask(
                        document_id=row.id,
                        org_id=org,
                        opened_at=created + timedelta(minutes=2),
                        sla_minutes=240,
                        due_at=created + timedelta(hours=4),
                        completed_at=(
                            created + timedelta(minutes=2 + minutes)
                            if minutes is not None
                            else None
                        ),
                        outcome=outcome,
                    )
                )
            if restricted:
                session.add(
                    InvoiceMetadata(document_id=row.id, org_id=org, visibility="restricted")
                )
            if name == "done.pdf":
                session.add(
                    FieldCorrection(
                        org_id=org,
                        document_id=row.id,
                        field_id=ids[0],
                        field_name="field_0",
                        kind="edit",
                        before_value="0",
                        after_value="zero",
                        reviewer_user_id=actors["admin"],
                        created_at=created + timedelta(minutes=10),
                    )
                )
                session.add(
                    FieldCorrection(
                        org_id=org,
                        document_id=row.id,
                        field_id=ids[1],
                        field_name="field_1",
                        kind="accept",
                        before_value="1",
                        after_value="1",
                        reviewer_user_id=actors["admin"],
                        created_at=created + timedelta(minutes=11),
                    )
                )
            return row

        auto = document("auto.pdf", "auto_approved", 1, fields=3)
        document("open.pdf", "needs_review", 0, fields=2, task=(None, None))
        done = document("done.pdf", "approved", 2, fields=4, task=(30, "approved"))
        document(
            "rejected.pdf",
            "rejected",
            3,
            fields=1,
            task=(10, "rejected"),
            document_type="purchase_order",
        )
        document("failed.pdf", "failed", 0, fields=0)
        document("queued.pdf", "queued", 0, fields=0)
        document("old.pdf", "approved", 45, fields=5, task=(60, "approved"))
        restricted = document(
            "restricted.pdf", "auto_approved", 1, fields=2, restricted=True, owner=actors["admin"]
        )
        document(
            "outside.pdf", "auto_approved", 0, fields=9, org=other_org, owner=actors["external"]
        )
        for index, (subject, status) in enumerate(
            (
                (auto, "proposed"),
                (restricted, "proposed"),
                (done, "dead_lettered"),
                (done, "failed"),
                (auto, "succeeded"),
            )
        ):
            session.add(
                Action(
                    org_id=org_id,
                    document_id=subject.id,
                    action_type="export_csv",
                    destination=f"dest-{index}",
                    payload_json="{}",
                    preview_json="{}",
                    status=status,
                    policy_mode="auto",
                    idempotency_key=f"key-{index}",
                    proposed_at=NOW,
                )
            )
        session.commit()
    with TestClient(app) as client:
        state = Metrics(client, engine, actors, org_id)

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
        try:
            yield state
        finally:
            app.dependency_overrides.pop(current_session, None)
    engine.dispose()


def test_overview_definitions_over_thirty_days(metrics: Metrics) -> None:
    body = metrics.overview()
    assert body["range"] == {
        "days": 30,
        "start": (TODAY - timedelta(days=29)).isoformat(),
        "end": TODAY.isoformat(),
        "document_type": None,
    }
    # auto, open, done, rejected and the restricted auto-approved document; failed, queued
    # and the 45-day-old document are out.
    assert body["documents_processed"] == 5
    assert body["auto_approve_rate"] == 0.4
    # 12 fields assessed, one edited (an accept is not a correction).
    assert body["field_accuracy"] == 0.9167
    # Durations: 0, 0 (auto), 30, 10; the open task is excluded.
    assert body["median_time_to_complete_minutes"] == 5.0
    assert body["review_queue_depth"] == 1
    assert body["cost_per_document"] is None
    assert body["baseline_minutes"] == 12
    # 5 documents x 12 minutes = 60 minutes, minus 40 minutes of actual review.
    assert body["hours_saved"] == 0.33
    series = body["series"]
    assert len(series) == 30 and series[0]["day"] == body["range"]["start"]
    assert sum(point["documents"] for point in series) == 5
    by_day = {point["day"]: point for point in series}
    assert by_day[TODAY.isoformat()] == {
        "day": TODAY.isoformat(),
        "documents": 1,
        "auto_approved": 0,
        "needs_review": 1,
        "corrected_fields": 0,
        "total_fields": 2,
        "completed": 0,
        "review_minutes": 0.0,
    }
    assert by_day[(TODAY - timedelta(days=2)).isoformat()] == {
        "day": (TODAY - timedelta(days=2)).isoformat(),
        "documents": 1,
        "auto_approved": 0,
        "needs_review": 1,
        "corrected_fields": 1,
        "total_fields": 4,
        "completed": 1,
        "review_minutes": 30.0,
    }
    yesterday = by_day[(TODAY - timedelta(days=1)).isoformat()]
    assert (yesterday["documents"], yesterday["auto_approved"], yesterday["total_fields"]) == (
        2,
        2,
        5,
    )


def test_overview_filters_and_access_scoping(metrics: Metrics) -> None:
    orders = metrics.overview(document_type="purchase_order")
    assert orders["documents_processed"] == 1 and orders["auto_approve_rate"] == 0.0
    assert orders["median_time_to_complete_minutes"] == 10.0
    assert orders["review_queue_depth"] == 0 and orders["field_accuracy"] == 1.0
    assert orders["hours_saved"] == 0.03 and orders["range"]["document_type"] == "purchase_order"

    quarter = metrics.overview(days=90)
    assert quarter["documents_processed"] == 6 and len(quarter["series"]) == 90
    assert quarter["median_time_to_complete_minutes"] == 10.0

    week = metrics.overview(days=1)
    assert week["documents_processed"] == 1 and week["auto_approve_rate"] == 0.0
    assert week["median_time_to_complete_minutes"] is None and len(week["series"]) == 1

    empty = metrics.overview(document_type="delivery_note")
    assert empty["documents_processed"] == 0 and empty["auto_approve_rate"] is None
    assert empty["field_accuracy"] is None and empty["hours_saved"] == 0.0

    metrics.actor = "member"
    member = metrics.overview()
    assert member["documents_processed"] == 4 and member["auto_approve_rate"] == 0.25
    assert member["field_accuracy"] == 0.9

    metrics.actor = "external"
    outside = metrics.overview()
    assert outside["documents_processed"] == 1 and outside["review_queue_depth"] == 0

    for params in ({"days": 0}, {"days": 366}, {"document_type": "Bad Type"}):
        assert metrics.client.get("/v1/metrics/overview", params=params).status_code == 422


def test_actions_summary_counts_by_status_for_visible_documents(metrics: Metrics) -> None:
    summary = metrics.client.get("/v1/actions/summary")
    assert summary.status_code == 200, summary.text
    body = summary.json()
    assert body["pending_approvals"] == 2 and body["dead_letters"] == 1 and body["failed"] == 1
    assert body["counts"]["proposed"] == 2 and body["counts"]["succeeded"] == 1
    assert body["counts"]["rejected"] == 0 and len(body["counts"]) == 10
    metrics.actor = "member"
    assert metrics.client.get("/v1/actions/summary").json()["pending_approvals"] == 1
    metrics.actor = "external"
    assert metrics.client.get("/v1/actions/summary").json()["counts"]["proposed"] == 0
    assert (
        json.loads(metrics.client.get(f"/v1/actions/{uuid.uuid4()}").text)["error"]["code"]
        == "not_found"
    )
