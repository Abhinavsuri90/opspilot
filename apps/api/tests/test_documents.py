import hashlib
import json
import os
import threading
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.db import SessionLocal, engine, set_org_context
from app.llm.provider import ExtractionError, MockInvoiceProvider, OpenRouterInvoiceProvider
from app.main import app
from app.models import Document, ExtractionRun, Organization, OutboxEvent
from app.storage import get_store
from app.worker import Claim, claim_next, complete, fail, process_one
from app.worker import main as worker_main

SAMPLE = Path(__file__).parents[3] / "examples" / "northwind-invoice.pdf"


class MemoryStore:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put(self, key: str, data: bytes) -> None:
        self.objects[key] = data

    def get(self, key: str) -> bytes:
        return self.objects[key]


def test_mock_provider_returns_grounded_invoice_fields() -> None:
    fields = MockInvoiceProvider().extract(SAMPLE.read_bytes())
    assert {field.name: field.value for field in fields} == {
        "vendor": "Northwind Traders",
        "invoice_number": "NW-2026-001",
        "invoice_date": "2026-09-26",
        "total": "$123.45",
    }
    assert all(field.evidence.endswith(field.value) and field.page_number == 1 for field in fields)


def test_worker_exits_on_invalid_provider_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def invalid_provider() -> MockInvoiceProvider:
        raise RuntimeError("provider is not configured")

    monkeypatch.setattr("app.worker.get_provider", invalid_provider)
    with pytest.raises(RuntimeError, match="provider is not configured"):
        worker_main()


def test_openrouter_provider_uses_schema_and_rejects_ungrounded_values() -> None:
    def response(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["model"] == "google/gemini-3.8-flash"
        assert payload["response_format"]["type"] == "json_schema"
        assert payload["provider"]["require_parameters"] is True
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "fields": [
                                        {
                                            "name": "total",
                                            "value": "$123.45",
                                            "evidence": "Total: $123.45",
                                            "page_number": 1,
                                        }
                                    ]
                                }
                            )
                        }
                    }
                ]
            },
        )

    with httpx.Client(transport=httpx.MockTransport(response)) as client:
        provider = OpenRouterInvoiceProvider("test-only-key", "google/gemini-3.8-flash", client)
        assert provider.extract(SAMPLE.read_bytes())[0].value == "$123.45"

    def ungrounded(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "fields": [
                                        {
                                            "name": "total",
                                            "value": "$999.99",
                                            "evidence": "Total: $999.99",
                                            "page_number": 1,
                                        }
                                    ]
                                }
                            )
                        }
                    }
                ]
            },
        )

    with httpx.Client(transport=httpx.MockTransport(ungrounded)) as client:
        provider = OpenRouterInvoiceProvider("test-only-key", "google/gemini-3.8-flash", client)
        with pytest.raises(ExtractionError):
            provider.extract(SAMPLE.read_bytes())


@pytest.mark.skipif("DATABASE_OWNER_URL" not in os.environ, reason="Postgres integration test")
def test_upload_dedup_extraction_and_tenant_visibility(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.worker.get_provider", MockInvoiceProvider)
    store = MemoryStore()
    app.dependency_overrides[get_store] = lambda: store
    invoice_number = uuid.uuid4().hex[:11].upper()
    data = SAMPLE.read_bytes().replace(b"NW-2026-001", invoice_number.encode("ascii"))
    try:
        with TestClient(app) as client:
            login = client.post(
                "/v1/auth/login",
                json={
                    "org_slug": "northwind",
                    "email": "northwind@example.com",
                    "password": os.environ["DEMO_PASSWORD"],
                },
            )
            assert login.status_code == 200
            org_id = uuid.UUID(login.json()["org_id"])
            with SessionLocal() as session:
                set_org_context(session, org_id)
                existing_count = session.scalar(
                    select(func.count()).select_from(Document).where(Document.org_id == org_id)
                ) or 0
            monkeypatch.setattr(
                "app.document_service.get_settings",
                lambda: SimpleNamespace(max_documents_per_org=existing_count + 1),
            )

            invalid = client.post(
                "/v1/documents", files={"file": ("fake.pdf", b"not a PDF", "application/pdf")}
            )
            assert invalid.status_code == 400
            assert store.objects == {}

            malformed = client.post(
                "/v1/documents",
                files={"file": ("broken.pdf", b"%PDF-broken document", "application/pdf")},
            )
            assert malformed.status_code == 400
            assert store.objects == {}

            uploaded = client.post(
                "/v1/documents", files={"file": ("invoice.pdf", data, "application/pdf")}
            )
            assert uploaded.status_code == 202, uploaded.text
            assert uploaded.json()["status"] == "queued"
            assert uploaded.json()["duplicate"] is False
            document_id = uploaded.json()["id"]
            assert len(store.objects) == 1

            duplicate = client.post(
                "/v1/documents", files={"file": ("renamed.pdf", data, "application/pdf")}
            )
            assert duplicate.status_code == 202
            assert duplicate.json()["id"] == document_id
            assert duplicate.json()["duplicate"] is True

            another = SAMPLE.read_bytes().replace(
                b"NW-2026-001", uuid.uuid4().hex[:11].upper().encode("ascii")
            )
            at_limit = client.post(
                "/v1/documents", files={"file": ("another.pdf", another, "application/pdf")}
            )
            assert at_limit.status_code == 409
            assert len(store.objects) == 1

            assert process_one(store, uuid.UUID(document_id)) is True
            detail = client.get(f"/v1/documents/{document_id}")
            assert detail.status_code == 200
            assert detail.json()["status"] == "needs_review"
            fields = {field["name"]: field for field in detail.json()["fields"]}
            assert fields["invoice_number"]["value"] == invoice_number
            assert fields["invoice_number"]["evidence"].endswith(invoice_number)
            assert any(row["id"] == document_id for row in client.get("/v1/documents").json())

            other_login = client.post(
                "/v1/auth/login",
                json={
                    "org_slug": "contoso",
                    "email": "contoso@example.com",
                    "password": os.environ["DEMO_PASSWORD"],
                },
            )
            assert other_login.status_code == 200
            assert client.get(f"/v1/documents/{document_id}").status_code == 404
            assert all(row["id"] != document_id for row in client.get("/v1/documents").json())
    finally:
        del app.dependency_overrides[get_store]


@pytest.mark.skipif("DATABASE_OWNER_URL" not in os.environ, reason="Postgres integration test")
def test_worker_rejects_corrupted_stored_document(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.worker.get_provider", MockInvoiceProvider)
    store = MemoryStore()
    app.dependency_overrides[get_store] = lambda: store
    data = SAMPLE.read_bytes().replace(b"NW-2026-001", uuid.uuid4().hex[:11].upper().encode())
    try:
        with TestClient(app) as client:
            login = client.post(
                "/v1/auth/login",
                json={
                    "org_slug": "northwind",
                    "email": "northwind@example.com",
                    "password": os.environ["DEMO_PASSWORD"],
                },
            )
            assert login.status_code == 200
            uploaded = client.post(
                "/v1/documents", files={"file": ("invoice.pdf", data, "application/pdf")}
            )
            assert uploaded.status_code == 202, uploaded.text
            document_id = uuid.UUID(uploaded.json()["id"])
            key = next(iter(store.objects))
            store.objects[key] = data[:-1] + b"X"

            assert process_one(store, document_id)
            detail = client.get(f"/v1/documents/{document_id}")
            assert detail.status_code == 200
            assert detail.json()["status"] == "failed"
            assert detail.json()["failure_reason"] == "Stored document failed integrity check"
            assert detail.json()["fields"] == []
    finally:
        del app.dependency_overrides[get_store]


@pytest.mark.skipif("DATABASE_OWNER_URL" not in os.environ, reason="Postgres integration test")
def test_worker_rotates_tenants_even_when_one_has_a_backlog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.worker.get_provider", MockInvoiceProvider)
    monkeypatch.setattr("app.worker._last_org_id", None)
    store = MemoryStore()
    data = SAMPLE.read_bytes()
    store.put("fairness.pdf", data)
    with SessionLocal() as session:
        org_ids = list(session.scalars(select(Organization.id).order_by(Organization.id)))
    assert len(org_ids) >= 2

    claimed_orgs: list[uuid.UUID] = []

    def claim_with_backlog(org_id: uuid.UUID, document_id: uuid.UUID | None = None) -> Claim:
        claimed_orgs.append(org_id)
        return Claim(
            org_id,
            uuid.uuid4(),
            uuid.uuid4(),
            "fairness.pdf",
            hashlib.sha256(data).hexdigest(),
            len(data),
            datetime.now(UTC),
            1,
        )

    monkeypatch.setattr("app.worker.claim_next", claim_with_backlog)
    monkeypatch.setattr("app.worker.complete", lambda claim, fields, provider: None)
    assert process_one(store)
    assert process_one(store)
    assert claimed_orgs == org_ids[:2]


@pytest.mark.skipif("DATABASE_OWNER_URL" not in os.environ, reason="Postgres integration test")
def test_worker_lease_lock_prevents_reclaim_during_completion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = MemoryStore()
    app.dependency_overrides[get_store] = lambda: store
    data = SAMPLE.read_bytes().replace(b"NW-2026-001", uuid.uuid4().hex[:11].upper().encode())
    try:
        with TestClient(app) as client:
            login = client.post(
                "/v1/auth/login",
                json={
                    "org_slug": "northwind",
                    "email": "northwind@example.com",
                    "password": os.environ["DEMO_PASSWORD"],
                },
            )
            assert login.status_code == 200
            org_id = uuid.UUID(login.json()["org_id"])
            uploaded = client.post(
                "/v1/documents", files={"file": ("invoice.pdf", data, "application/pdf")}
            )
            assert uploaded.status_code == 202, uploaded.text
            document_id = uuid.UUID(uploaded.json()["id"])
            claim = claim_next(org_id, document_id)
            assert claim is not None

            # Simulate a long-running worker with an expired lease.
            stale_at = datetime.now(UTC) - timedelta(minutes=6)
            with SessionLocal() as session, session.begin():
                set_org_context(session, org_id)
                event = session.get(OutboxEvent, claim.event_id)
                assert event is not None
                event.claimed_at = stale_at
            stale_claim = replace(claim, claimed_at=stale_at)

            entered = threading.Event()
            proceed = threading.Event()
            errors: list[Exception] = []

            class PausingSession(Session):
                def get(self, entity: Any, ident: Any, **kwargs: Any) -> Any:
                    row = super().get(entity, ident, **kwargs)
                    if threading.current_thread().name == "completer" and entity is OutboxEvent:
                        entered.set()
                        if not proceed.wait(timeout=10):
                            raise TimeoutError("Test completion gate timed out")
                    return row

            monkeypatch.setattr(
                "app.worker.SessionLocal",
                sessionmaker(bind=engine, class_=PausingSession, expire_on_commit=False),
            )

            def finish() -> None:
                try:
                    complete(
                        stale_claim, MockInvoiceProvider().extract(data), MockInvoiceProvider()
                    )
                except Exception as exc:
                    errors.append(exc)

            thread = threading.Thread(target=finish, name="completer")
            thread.start()
            try:
                assert entered.wait(timeout=10)
                # A second worker skips the locked lease instead of running twice.
                assert claim_next(org_id, document_id) is None
            finally:
                proceed.set()
                thread.join(timeout=10)
            assert not thread.is_alive()
            assert not errors
            assert client.get(f"/v1/documents/{document_id}").json()["status"] == "needs_review"
            with SessionLocal() as session:
                set_org_context(session, org_id)
                runs = session.scalars(
                    select(ExtractionRun).where(ExtractionRun.document_id == document_id)
                ).all()
                assert len(runs) == 1
    finally:
        del app.dependency_overrides[get_store]


@pytest.mark.skipif("DATABASE_OWNER_URL" not in os.environ, reason="Postgres integration test")
def test_failed_document_can_be_retried_without_reuploading(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.worker.get_provider", MockInvoiceProvider)
    store = MemoryStore()
    app.dependency_overrides[get_store] = lambda: store
    data = SAMPLE.read_bytes().replace(b"NW-2026-001", uuid.uuid4().hex[:11].upper().encode())
    try:
        with TestClient(app) as client:
            login = client.post(
                "/v1/auth/login",
                json={
                    "org_slug": "northwind",
                    "email": "northwind@example.com",
                    "password": os.environ["DEMO_PASSWORD"],
                },
            )
            assert login.status_code == 200
            org_id = uuid.UUID(login.json()["org_id"])
            uploaded = client.post(
                "/v1/documents", files={"file": ("retry.pdf", data, "application/pdf")}
            )
            assert uploaded.status_code == 202, uploaded.text
            document_id = uuid.UUID(uploaded.json()["id"])
            claim = claim_next(org_id, document_id)
            assert claim is not None
            fail(claim, "Provider temporarily unavailable", retryable=False)
            assert client.get(f"/v1/documents/{document_id}").json()["status"] == "failed"

            duplicate = client.post(
                "/v1/documents", files={"file": ("retry.pdf", data, "application/pdf")}
            )
            assert duplicate.status_code == 202
            assert duplicate.json()["duplicate"] is True
            assert duplicate.json()["status"] == "failed"

            retried = client.post(f"/v1/documents/{document_id}/retry")
            assert retried.status_code == 202
            assert retried.json()["status"] == "queued"
            assert retried.json()["failure_reason"] is None
            assert client.post(f"/v1/documents/{document_id}/retry").status_code == 409

            assert process_one(store, document_id) is True
            detail = client.get(f"/v1/documents/{document_id}")
            assert detail.json()["status"] == "needs_review"
            assert detail.json()["fields"]

            other_login = client.post(
                "/v1/auth/login",
                json={
                    "org_slug": "contoso",
                    "email": "contoso@example.com",
                    "password": os.environ["DEMO_PASSWORD"],
                },
            )
            assert other_login.status_code == 200
            assert client.post(f"/v1/documents/{document_id}/retry").status_code == 404
    finally:
        del app.dependency_overrides[get_store]


@pytest.mark.skipif("DATABASE_OWNER_URL" not in os.environ, reason="Postgres integration test")
def test_manual_retry_limit_blocks_third_request() -> None:
    store = MemoryStore()
    app.dependency_overrides[get_store] = lambda: store
    data = SAMPLE.read_bytes().replace(b"NW-2026-001", uuid.uuid4().hex[:11].upper().encode())
    try:
        with TestClient(app) as client:
            login = client.post(
                "/v1/auth/login",
                json={
                    "org_slug": "northwind",
                    "email": "northwind@example.com",
                    "password": os.environ["DEMO_PASSWORD"],
                },
            )
            assert login.status_code == 200
            org_id = uuid.UUID(login.json()["org_id"])
            uploaded = client.post(
                "/v1/documents", files={"file": ("retry-limit.pdf", data, "application/pdf")}
            )
            assert uploaded.status_code == 202, uploaded.text
            document_id = uuid.UUID(uploaded.json()["id"])

            for manual_retry in range(3):
                claim = claim_next(org_id, document_id)
                assert claim is not None
                fail(claim, "Provider unavailable", retryable=False)
                if manual_retry < 2:
                    retried = client.post(f"/v1/documents/{document_id}/retry")
                    assert retried.status_code == 202

            exhausted = client.post(f"/v1/documents/{document_id}/retry")
            assert exhausted.status_code == 409
            assert exhausted.json()["error"] == {
                "code": "retry_limit_reached",
                "message": "Manual retry limit reached for this document",
                "details": None,
            }
            with SessionLocal() as session:
                set_org_context(session, org_id)
                event_count = session.scalar(
                    select(func.count())
                    .select_from(OutboxEvent)
                    .where(OutboxEvent.document_id == document_id)
                )
                assert event_count == 3
    finally:
        del app.dependency_overrides[get_store]
