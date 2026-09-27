"""The daily model budget: status, the next window, the audit, and the worker's two outcomes."""

import json
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from scripts.generate_demo_invoice import invoice_pdf
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.action_models import OrgSettings
from app.db import SessionLocal, set_org_context
from app.learning_models import LlmCall
from app.llm import budget
from app.llm.provider import MockInvoiceProvider
from app.main import app
from app.models import AuditEvent, Base, Document, ExtractionRun, Organization, OutboxEvent
from app.storage import get_store
from app.worker import process_one
from tests.conftest import TenantFactory, owner_engine, postgres
from tests.test_documents import MemoryStore, audit_events, tenant_login, upload


class PaidMock(MockInvoiceProvider):
    """The mock extractor presented as a paid provider so the budget applies to it."""

    name = "openrouter"
    paid = True


def add_call(session: Session, org_id: uuid.UUID, cost: str | None, at: datetime) -> None:
    session.add(
        LlmCall(
            org_id=org_id,
            document_id=None,
            purpose="extraction",
            provider="openrouter",
            model="m",
            prompt_version="p",
            tokens_in=1,
            tokens_out=1,
            cost_cents=Decimal(cost) if cost is not None else None,
            latency_ms=1,
            ok=True,
            error=None,
            trace_id=None,
            created_at=at,
        )
    )


@pytest.fixture
def store() -> Iterator[tuple[Session, uuid.UUID]]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    org_id = uuid.uuid4()
    with Session(engine) as session:
        session.add(Organization(id=org_id, slug="budget", name="Budget"))
        session.commit()
        yield session, org_id
    engine.dispose()


def test_status_sums_todays_priced_calls_against_the_cap(
    store: tuple[Session, uuid.UUID],
) -> None:
    session, org_id = store
    now = datetime(2026, 9, 27, 15, 30, tzinfo=UTC)
    assert budget.status(session, org_id, now) == budget.BudgetStatus(None, Decimal("0"), False)
    session.add(OrgSettings(org_id=org_id, daily_llm_spend_cap_cents=100, updated_at=now))
    add_call(session, org_id, "60.5", now - timedelta(hours=1))
    add_call(session, org_id, None, now - timedelta(hours=1))
    add_call(session, org_id, "500", now - timedelta(days=1, minutes=1))
    session.commit()
    state = budget.status(session, org_id, now)
    assert state == budget.BudgetStatus(100, Decimal("60.5000"), False)
    assert budget.allows(session, org_id, now)
    add_call(session, org_id, "39.5", now)
    session.commit()
    state = budget.status(session, org_id, now)
    assert state.exhausted and state.spent_cents == Decimal("100.0000")
    assert not budget.allows(session, org_id, now)
    assert budget.next_window_start(now) == datetime(2026, 9, 28, 0, 5, tzinfo=UTC)
    assert budget.day_start(now) == datetime(2026, 9, 27, tzinfo=UTC)
    assert budget.audit_exhausted(session, org_id, state, now, "deferred") is True
    assert budget.audit_exhausted(session, org_id, state, now + timedelta(hours=2), "x") is False
    tomorrow = now + timedelta(days=1)
    assert budget.audit_exhausted(session, org_id, state, tomorrow, "deferred") is True
    session.commit()
    events = session.scalars(select(AuditEvent).order_by(AuditEvent.created_at)).all()
    assert [event.event_type for event in events] == [budget.BUDGET_REACHED_EVENT] * 2
    assert json.loads(events[0].detail_json) == {
        "cap_cents": 100,
        "spent_cents": "100.0000",
        "outcome": "deferred",
        "resumes_at": "2026-09-28T00:05:00+00:00",
    }


def set_cap(org_id: uuid.UUID, cap: int, spent: str) -> None:
    with Session(owner_engine()) as session, session.begin():
        session.add(OrgSettings(org_id=org_id, daily_llm_spend_cap_cents=cap))
        add_call(session, org_id, spent, datetime.now(UTC))


@postgres
def test_worker_defers_the_document_to_the_next_day_when_the_budget_is_spent(
    monkeypatch: pytest.MonkeyPatch, make_tenant: TenantFactory
) -> None:
    monkeypatch.setattr("app.worker.get_provider", PaidMock)
    tenant = make_tenant()
    set_cap(tenant.org_id, 50, "50")
    store = MemoryStore()
    app.dependency_overrides[get_store] = lambda: store
    try:
        with TestClient(app) as client:
            tenant_login(client, tenant, "member")
            first = uuid.UUID(upload(client, "one.pdf", invoice_pdf(invoice_number="B-1"))["id"])
            second = uuid.UUID(upload(client, "two.pdf", invoice_pdf(invoice_number="B-2"))["id"])
            assert process_one(store, first) is True
            assert process_one(store, second) is True
            assert process_one(store, first) is False  # not available before tomorrow
            with SessionLocal() as session:
                set_org_context(session, tenant.org_id)
                for document_id in (first, second):
                    document = session.get(Document, document_id)
                    event = session.scalar(
                        select(OutboxEvent).where(OutboxEvent.document_id == document_id)
                    )
                    assert document is not None and event is not None
                    assert document.status == "queued"
                    assert document.failure_reason == "Daily model budget reached"
                    assert event.attempts == 0 and event.claimed_at is None
                    assert event.available_at == budget.next_window_start(datetime.now(UTC))
                assert session.scalars(select(ExtractionRun)).all() == []
                org_events = session.scalars(
                    select(AuditEvent).where(
                        AuditEvent.event_type == budget.BUDGET_REACHED_EVENT,
                        AuditEvent.document_id.is_(None),
                    )
                ).all()
                assert len(org_events) == 1  # once per day, not once per document
                assert json.loads(org_events[0].detail_json)["outcome"] == "deferred"
            events = audit_events(tenant.org_id, first)
            assert [event for event, _ in events][-2:] == [
                "document.extracting",
                "document.budget_deferred",
            ]
            assert events[-1][1]["reason"] == "Daily model budget reached"
            body = client.get(f"/v1/documents/{first}").json()
            assert body["status"] == "queued"
            assert body["failure_reason"] == "Daily model budget reached"
            # Raising the budget and releasing the event lets the document through.
            with Session(owner_engine()) as session, session.begin():
                settings = session.get(OrgSettings, tenant.org_id)
                assert settings is not None
                settings.daily_llm_spend_cap_cents = None
                for event in session.scalars(
                    select(OutboxEvent).where(OutboxEvent.document_id == first)
                ):
                    event.available_at = datetime.now(UTC) - timedelta(seconds=1)
            assert process_one(store, first) is True
            body = client.get(f"/v1/documents/{first}").json()
            assert body["status"] == "needs_review" and body["failure_reason"] is None
    finally:
        del app.dependency_overrides[get_store]


@postgres
def test_worker_falls_back_to_the_rules_provider_when_configured(
    monkeypatch: pytest.MonkeyPatch, make_tenant: TenantFactory
) -> None:
    monkeypatch.setattr("app.worker.get_provider", PaidMock)
    monkeypatch.setattr(
        "app.worker.get_settings",
        lambda: SimpleNamespace(extraction_timeout_seconds=60, llm_budget_fallback="rules"),
    )
    tenant = make_tenant()
    set_cap(tenant.org_id, 10, "10")
    store = MemoryStore()
    app.dependency_overrides[get_store] = lambda: store
    try:
        with TestClient(app) as client:
            tenant_login(client, tenant, "member")
            uploaded = upload(client, "r.pdf", invoice_pdf(invoice_number="R-1"))
            document_id = uuid.UUID(uploaded["id"])
            assert process_one(store, document_id) is True
            body = client.get(f"/v1/documents/{document_id}").json()
            assert body["status"] == "needs_review" and body["provider"] == "rules"
            with SessionLocal() as session:
                set_org_context(session, tenant.org_id)
                run = session.scalar(select(ExtractionRun))
                assert run is not None and run.provider == "rules" and run.escalated is False
                assert run.tier1_model == "invoice-pattern-v2" and run.cost_cents == Decimal("0")
                calls = session.scalars(
                    select(LlmCall).where(LlmCall.document_id == document_id)
                ).all()
                assert [(call.provider, call.cost_cents) for call in calls] == [
                    ("rules", Decimal("0.0000"))
                ]
                org_events = session.scalars(
                    select(AuditEvent).where(AuditEvent.event_type == budget.BUDGET_REACHED_EVENT)
                ).all()
                assert [json.loads(event.detail_json)["outcome"] for event in org_events] == [
                    "rules_fallback"
                ]
    finally:
        del app.dependency_overrides[get_store]


@postgres
def test_free_providers_ignore_the_budget(
    monkeypatch: pytest.MonkeyPatch, make_tenant: TenantFactory
) -> None:
    monkeypatch.setattr("app.worker.get_provider", MockInvoiceProvider)
    tenant = make_tenant()
    set_cap(tenant.org_id, 0, "0")
    store = MemoryStore()
    app.dependency_overrides[get_store] = lambda: store
    try:
        with TestClient(app) as client:
            tenant_login(client, tenant, "member")
            uploaded = upload(client, "f.pdf", invoice_pdf(invoice_number="F-1"))
            document_id = uuid.UUID(uploaded["id"])
            assert process_one(store, document_id) is True
            assert client.get(f"/v1/documents/{document_id}").json()["status"] == "needs_review"
    finally:
        del app.dependency_overrides[get_store]
