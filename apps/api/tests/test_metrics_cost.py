"""Cost, token, escalation and weekly accuracy KPIs from the ledger and extraction runs."""

import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.auth import current_session
from app.learning_models import LlmCall
from app.main import app
from app.models import Base, Document, ExtractionRun, Membership, Organization, User, WorkflowConfig
from app.workflow_config import default_invoice_config
from app.workflow_models import FieldCorrection
from tests.test_review import add_fields, make_document

TODAY = datetime.now(UTC).date()


def at_days_ago(days: int) -> datetime:
    return datetime.combine(TODAY - timedelta(days=days), datetime.min.time(), tzinfo=UTC).replace(
        hour=9
    )


@dataclass
class Cost:
    client: TestClient
    engine: Engine
    org_id: uuid.UUID
    actors: dict[str, uuid.UUID]
    actor: str = "admin"

    def get(self, path: str, **params: object) -> Any:
        response = self.client.get(path, params=params)
        assert response.status_code == 200, response.text
        return response.json()


@pytest.fixture
def cost() -> Iterator[Cost]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    org_id, other_org = uuid.uuid4(), uuid.uuid4()
    actors = {name: uuid.uuid4() for name in ("admin", "external")}
    with Session(engine) as session:
        session.add_all(
            [
                Organization(id=org_id, slug="cost", name="Cost"),
                Organization(id=other_org, slug="other", name="Other"),
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
                    role="admin",
                    status="active",
                )
            )
        config = default_invoice_config()
        for target in (org_id, other_org):
            session.add(
                WorkflowConfig(org_id=target, version=1, config_json=config.model_dump_json())
            )
        session.flush()

        def document(
            name: str, days_ago: int, *, org: uuid.UUID = org_id, escalated: bool = False,
            calls: list[tuple[str | None, int | None, int | None, bool]] = (),  # type: ignore[assignment]
            corrected: int = 0, fields: int = 3, status: str = "approved",
        ) -> Document:
            created = at_days_ago(days_ago)
            owner = actors["external"] if org == other_org else actors["admin"]
            row = make_document(org, owner, name, status, created)
            session.add(row)
            session.flush()
            rows = [{"name": f"f{i}", "value": str(i)} for i in range(fields)]
            ids = [f.id for f in add_fields(session, org, row, rows, created)]
            run = session.scalar(
                select(ExtractionRun).where(ExtractionRun.document_id == row.id)
            )
            assert run is not None
            run.escalated = escalated
            run.tier1_model = "openai/gpt-4o-mini"
            run.tier2_model = "openai/gpt-4.1" if escalated else None
            for index in range(corrected):
                session.add(
                    FieldCorrection(
                        org_id=org, document_id=row.id, field_id=ids[index], field_name=f"f{index}",
                        kind="edit", before_value=str(index), after_value="fixed",
                        reviewer_user_id=owner, created_at=created + timedelta(minutes=5),
                    )
                )
            for cost_cents, tokens_in, tokens_out, ok in calls:
                session.add(
                    LlmCall(
                        org_id=org, document_id=row.id, purpose="extraction",
                        provider="openrouter", model="openai/gpt-4o-mini",
                        prompt_version="extraction-v3", tokens_in=tokens_in,
                        tokens_out=tokens_out,
                        cost_cents=Decimal(cost_cents) if cost_cents is not None else None,
                        latency_ms=100, ok=ok, error=None if ok else "HTTP 500",
                        trace_id=None, created_at=created,
                    )
                )
            return row

        # This week: two documents, one escalated, one unpriced call, one corrected field.
        document(
            "a.pdf",
            0,
            calls=[("1.5", 1000, 100, True), ("0.5", 300, 50, True)],
            escalated=True,
            corrected=1,
        )
        document("b.pdf", 1, calls=[(None, 200, 20, True), ("0.25", 100, 10, False)])
        # Two weeks ago: an old, cheap, clean document; and a failed one that never counts.
        document("c.pdf", 14, calls=[("0.1", 50, 5, True)], corrected=0, fields=2)
        document("d.pdf", 14, calls=[("9", 50, 5, True)], status="failed")
        # Out of the 30-day range and in another organization.
        document("e.pdf", 40, calls=[("100", 1, 1, True)])
        document("f.pdf", 0, org=other_org, calls=[("100", 1, 1, True)], escalated=True)
        session.commit()
    with TestClient(app) as client:
        state = Cost(client, engine, org_id, actors)

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


def test_overview_reports_cost_tokens_and_escalation_from_the_ledger(cost: Cost) -> None:
    body = cost.get("/v1/metrics/overview")
    assert body["documents_processed"] == 3
    # 1.5 + 0.5 + 0.25 + 0.1 cents over three processed documents; one call is unpriced.
    assert body["cost_total_cents"] == 2.35
    assert body["cost_per_document"] == round(2.35 / 3, 4)
    assert body["cost_unpriced_calls"] == 1 and body["llm_calls"] == 5
    assert body["tokens_in"] == 1650 and body["tokens_out"] == 185
    assert body["escalation_rate"] == round(1 / 3, 4) and body["escalated_documents"] == 1
    assert body["field_accuracy"] == round(1 - 1 / 8, 4)

    week = cost.get("/v1/metrics/overview", days=1)
    assert week["documents_processed"] == 1 and week["cost_per_document"] == 2.0
    assert week["escalation_rate"] == 1.0

    quarter = cost.get("/v1/metrics/overview", days=90)
    assert quarter["documents_processed"] == 4 and quarter["cost_total_cents"] == 102.35

    empty = cost.get("/v1/metrics/overview", document_type="purchase_order")
    assert empty["cost_per_document"] is None and empty["escalation_rate"] is None
    assert empty["cost_total_cents"] == 0.0 and empty["llm_calls"] == 0

    cost.actor = "external"
    outside = cost.get("/v1/metrics/overview")
    assert outside["documents_processed"] == 1 and outside["cost_per_document"] == 100.0
    assert outside["escalation_rate"] == 1.0


def test_accuracy_series_is_weekly_oldest_first_and_scoped(cost: Cost) -> None:
    points = cost.get("/v1/metrics/accuracy")
    assert len(points) == 12
    this_week = TODAY - timedelta(days=TODAY.weekday())
    assert points[-1]["week_start"] == this_week.isoformat()
    assert points[0]["week_start"] == (this_week - timedelta(weeks=11)).isoformat()
    assert all(
        date.fromisoformat(point["week_start"]).weekday() == 0 for point in points
    )
    by_week = {point["week_start"]: point for point in points}
    latest = by_week[this_week.isoformat()]
    yesterday = TODAY - timedelta(days=1)
    yesterday_week = yesterday - timedelta(days=yesterday.weekday())
    if yesterday_week == this_week:
        assert latest == {
            "week_start": this_week.isoformat(),
            "fields_assessed": 6,
            "fields_corrected": 1,
            "accuracy": round(1 - 1 / 6, 4),
        }
    else:
        assert (latest["fields_assessed"], latest["fields_corrected"]) == (3, 1)
        assert by_week[yesterday_week.isoformat()]["fields_assessed"] == 3
    two_weeks = TODAY - timedelta(days=14)
    old_week = (two_weeks - timedelta(days=two_weeks.weekday())).isoformat()
    assert by_week[old_week] == {
        "week_start": old_week,
        "fields_assessed": 2,
        "fields_corrected": 0,
        "accuracy": 1.0,
    }
    # a, b, c and the 40-day-old e are inside twelve weeks; the failed d never counts.
    assert sum(point["fields_assessed"] for point in points) == 11
    empty_weeks = [point for point in points if point["fields_assessed"] == 0]
    assert all(point["accuracy"] is None for point in empty_weeks)

    short = cost.get("/v1/metrics/accuracy", weeks=1)
    assert len(short) == 1 and short[0]["week_start"] == this_week.isoformat()
    assert cost.get("/v1/metrics/accuracy", document_type="delivery_note") == [
        {**point, "fields_assessed": 0, "fields_corrected": 0, "accuracy": None}
        for point in points
    ]
    for params in ({"weeks": 0}, {"weeks": 53}, {"document_type": "Bad"}):
        assert cost.client.get("/v1/metrics/accuracy", params=params).status_code == 422

    cost.actor = "external"
    outside = cost.get("/v1/metrics/accuracy", weeks=2)
    assert sum(point["fields_assessed"] for point in outside) == 3
