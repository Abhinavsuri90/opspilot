import hashlib
import json
import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from scripts.generate_demo_invoice import invoice_pdf
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.db import SessionLocal, engine, set_org_context
from app.llm.provider import (
    ExtractionError,
    ExtractionResult,
    MockInvoiceProvider,
    OpenRouterInvoiceProvider,
)
from app.main import app
from app.models import AuditEvent, Document, ExtractionRun, Organization, OutboxEvent
from app.storage import get_store
from app.worker import Claim, assess, claim_next, complete, fail, process_one, stale_lease_seconds
from app.worker import main as worker_main
from app.workflow_config import (
    DocumentTypeSpec,
    FieldSpec,
    WorkflowConfigModel,
    default_invoice_config,
)
from app.workflow_models import FieldCorrection, ReviewTask
from tests.conftest import Tenant, TenantFactory, postgres

SAMPLE = Path(__file__).parents[3] / "examples" / "northwind-invoice.pdf"
CONFIG = default_invoice_config()


class MemoryStore:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put(self, key: str, data: bytes) -> None:
        self.objects[key] = data

    def get(self, key: str) -> bytes:
        return self.objects[key]


def demo_login(client: TestClient, slug: str = "northwind") -> dict[str, Any]:
    response = client.post(
        "/v1/auth/login",
        json={
            "org_slug": slug,
            "email": f"{slug}@example.com",
            "password": os.environ["DEMO_PASSWORD"],
        },
    )
    assert response.status_code == 200, response.text
    return dict(response.json())


def tenant_login(client: TestClient, tenant: Tenant, role: str = "admin") -> None:
    client.cookies.clear()
    client.cookies.set("opspilot_session", tenant.token(role))


def upload(client: TestClient, filename: str, data: bytes) -> dict[str, Any]:
    response = client.post("/v1/documents", files={"file": (filename, data, "application/pdf")})
    assert response.status_code == 202, response.text
    return dict(response.json())


def unique_sample() -> bytes:
    return SAMPLE.read_bytes().replace(b"NW-2026-001", uuid.uuid4().hex[:11].upper().encode())


def test_mock_provider_returns_grounded_invoice_fields() -> None:
    result = MockInvoiceProvider().extract(SAMPLE.read_bytes(), CONFIG)
    assert {field.name: field.value for field in result.fields} == {
        "vendor": "Northwind Traders",
        "invoice_number": "NW-2026-001",
        "invoice_date": "2026-09-26",
        "total": "$123.45",
    }
    assert all(
        field.evidence.endswith(field.value) and field.page_number == 1 for field in result.fields
    )
    assert all(field.self_confidence == 1.0 for field in result.fields)
    assert result.document_type == "invoice"
    assert result.prompt_version == "mock-v2" and result.model == "invoice-pattern-v2"
    assert result.tokens_in is None and result.latency_ms >= 0
    assert len(result.pages) == 1


def test_rules_provider_reads_configured_labels_and_detects_document_type() -> None:
    receipt = DocumentTypeSpec(
        name="receipt",
        detect=["receipt"],
        fields=[FieldSpec(name="merchant"), FieldSpec(name="amount", type="money")],
    )
    config = WorkflowConfigModel(document_types=[receipt, CONFIG.document_types[0]])
    data = invoice_pdf(
        invoice_number="PO-9",
        extra_lines={
            "Due Date": "2026-10-26",
            "Subtotal": "$100.00",
            "Tax": "$23.45",
            "Currency": "USD",
            "PO Number": "PO-2026-014",
        },
    )
    result = MockInvoiceProvider().extract(data, config)
    assert result.document_type == "invoice"
    assert {field.name: field.value for field in result.fields} == {
        "vendor": "Northwind Traders",
        "invoice_number": "PO-9",
        "invoice_date": "2026-09-26",
        "due_date": "2026-10-26",
        "subtotal": "$100.00",
        "tax": "$23.45",
        "total": "$123.45",
        "currency": "USD",
        "po_number": "PO-2026-014",
    }
    with pytest.raises(ExtractionError, match="No supported receipt fields"):
        MockInvoiceProvider().extract(data, WorkflowConfigModel(document_types=[receipt]))


def test_worker_exits_on_invalid_provider_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def invalid_provider() -> MockInvoiceProvider:
        raise RuntimeError("provider is not configured")

    monkeypatch.setattr("app.worker.get_provider", invalid_provider)
    with pytest.raises(RuntimeError, match="provider is not configured"):
        worker_main()


def openrouter_response(fields: list[dict[str, object]]) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": json.dumps({"fields": fields})}}],
            "usage": {"prompt_tokens": 321, "completion_tokens": 45},
        },
    )


def test_openrouter_provider_uses_config_schema_and_drops_ungrounded_fields() -> None:
    def response(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["model"] == "google/gemini-3.8-flash"
        assert payload["response_format"]["type"] == "json_schema"
        assert payload["provider"]["require_parameters"] is True
        schema = payload["response_format"]["json_schema"]["schema"]
        item = schema["properties"]["fields"]["items"]
        assert item["properties"]["name"]["enum"] == [
            field.name for field in CONFIG.document_types[0].fields
        ]
        assert "confidence" in item["required"]
        assert "Fields to extract" in payload["messages"][0]["content"]
        assert "po_number: PO Number (identifier)" in payload["messages"][0]["content"]
        return openrouter_response(
            [
                {
                    "name": "total",
                    "value": "$123.45",
                    "evidence": "Total: $123.45",
                    "page_number": 1,
                    "confidence": 0.9,
                },
                {
                    "name": "vendor",
                    "value": "Acme",
                    "evidence": "Vendor: Acme",
                    "page_number": 1,
                    "confidence": 0.9,
                },
            ]
        )

    with httpx.Client(transport=httpx.MockTransport(response)) as client:
        provider = OpenRouterInvoiceProvider("test-only-key", "google/gemini-3.8-flash", client)
        result = provider.extract(SAMPLE.read_bytes(), CONFIG)
    assert [(field.name, field.value, field.self_confidence) for field in result.fields] == [
        ("total", "$123.45", 0.9)
    ]
    assert result.notes == ["Dropped field 'vendor': evidence not found verbatim in the PDF"]
    assert result.tokens_in == 321 and result.tokens_out == 45
    assert result.prompt_version == "extraction-v2"

    def ungrounded(request: httpx.Request) -> httpx.Response:
        return openrouter_response(
            [
                {
                    "name": "total",
                    "value": "$999.99",
                    "evidence": "Total: $999.99",
                    "page_number": 1,
                    "confidence": 1,
                }
            ]
        )

    with httpx.Client(transport=httpx.MockTransport(ungrounded)) as client:
        provider = OpenRouterInvoiceProvider("test-only-key", "google/gemini-3.8-flash", client)
        with pytest.raises(ExtractionError, match="no field with matching PDF evidence"):
            provider.extract(SAMPLE.read_bytes(), CONFIG)


@postgres
def test_upload_dedup_extraction_and_tenant_visibility(
    monkeypatch: pytest.MonkeyPatch, demo_document_cleanup: None
) -> None:
    monkeypatch.setattr("app.worker.get_provider", MockInvoiceProvider)
    store = MemoryStore()
    app.dependency_overrides[get_store] = lambda: store
    invoice_number = uuid.uuid4().hex[:11].upper()
    data = SAMPLE.read_bytes().replace(b"NW-2026-001", invoice_number.encode("ascii"))
    try:
        with TestClient(app) as client:
            org_id = uuid.UUID(demo_login(client)["org_id"])
            with SessionLocal() as session:
                set_org_context(session, org_id)
                existing_count = (
                    session.scalar(
                        select(func.count()).select_from(Document).where(Document.org_id == org_id)
                    )
                    or 0
                )
            monkeypatch.setattr(
                "app.document_service.get_settings",
                lambda: SimpleNamespace(
                    max_documents_per_org=existing_count + 1, upload_parse_timeout_seconds=15
                ),
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

            uploaded = upload(client, "invoice.pdf", data)
            assert uploaded["status"] == "queued"
            assert uploaded["duplicate"] is False
            assert uploaded["document_type"] == "invoice"
            assert uploaded["flagged_count"] == 0
            document_id = uploaded["id"]
            assert len(store.objects) == 1

            duplicate = upload(client, "renamed.pdf", data)
            assert duplicate["id"] == document_id
            assert duplicate["duplicate"] is True

            at_limit = client.post(
                "/v1/documents",
                files={"file": ("another.pdf", unique_sample(), "application/pdf")},
            )
            assert at_limit.status_code == 409
            assert len(store.objects) == 1

            assert process_one(store, uuid.UUID(document_id)) is True
            detail = client.get(f"/v1/documents/{document_id}")
            assert detail.status_code == 200
            body = detail.json()
            assert body["status"] == "needs_review"
            assert body["provider"] == "mock" and body["version"] == 0
            fields = {field["name"]: field for field in body["fields"]}
            assert fields["invoice_number"]["value"] == invoice_number
            assert fields["invoice_number"]["current_value"] == invoice_number
            assert fields["invoice_number"]["evidence"].endswith(invoice_number)
            assert fields["invoice_number"]["label"] == "Invoice Number"
            assert fields["invoice_number"]["status"] == "auto"
            assert fields["total"]["confidence"] == 1.0 and fields["total"]["threshold"] == 0.9
            assert fields["total"]["signals"]["grounding"] == 1.0
            assert fields["total"]["signals"]["model_agreement"] is None
            assert fields["total"]["reasons"] == []
            assert body["flagged_count"] == 0
            assert body["review_task"]["overdue"] is False
            assert body["review_task"]["sla_minutes"] == 240
            assert body["review_task"]["outcome"] is None
            assert [rule["passed"] for rule in body["rule_results"]] == [None, None]
            listed = client.get("/v1/documents").json()
            assert any(row["id"] == document_id and row["flagged_count"] == 0 for row in listed)
            assert any(
                row["document_id"] == document_id for row in client.get("/v1/review/queue").json()
            )

            demo_login(client, "contoso")
            assert client.get(f"/v1/documents/{document_id}").status_code == 404
            assert client.get(f"/v1/documents/{document_id}/timeline").status_code == 404
            assert all(row["id"] != document_id for row in client.get("/v1/documents").json())
            assert all(
                row["document_id"] != document_id
                for row in client.get("/v1/review/queue").json()
            )
    finally:
        del app.dependency_overrides[get_store]


@postgres
def test_worker_rejects_corrupted_stored_document(
    monkeypatch: pytest.MonkeyPatch, demo_document_cleanup: None
) -> None:
    monkeypatch.setattr("app.worker.get_provider", MockInvoiceProvider)
    store = MemoryStore()
    app.dependency_overrides[get_store] = lambda: store
    data = unique_sample()
    try:
        with TestClient(app) as client:
            demo_login(client)
            document_id = uuid.UUID(upload(client, "invoice.pdf", data)["id"])
            key = next(iter(store.objects))
            store.objects[key] = data[:-1] + b"X"

            assert process_one(store, document_id)
            detail = client.get(f"/v1/documents/{document_id}")
            assert detail.status_code == 200
            assert detail.json()["status"] == "failed"
            assert detail.json()["failure_reason"] == "Stored document failed integrity check"
            assert detail.json()["fields"] == []
            assert detail.json()["review_task"] is None
            timeline = client.get(f"/v1/documents/{document_id}/timeline").json()
            assert [entry["event_type"] for entry in timeline] == [
                "document.received",
                "document.queued",
                "document.extracting",
                "document.failed",
            ]
            assert timeline[-1]["detail"]["reason"] == "Stored document failed integrity check"
    finally:
        del app.dependency_overrides[get_store]


@postgres
def test_worker_rotates_tenants_even_when_one_has_a_backlog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.worker.get_provider", MockInvoiceProvider)
    monkeypatch.setattr("app.worker._last_org_id", None)
    monkeypatch.setattr("app.worker.load_pinned_config", lambda org_id, version: CONFIG)
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
            1,
        )

    monkeypatch.setattr("app.worker.claim_next", claim_with_backlog)
    monkeypatch.setattr(
        "app.worker.complete",
        lambda claim, result, evaluation, type_spec, provider, config: None,
    )
    assert process_one(store)
    assert process_one(store)
    assert claimed_orgs == org_ids[:2]


@postgres
def test_worker_lease_lock_prevents_reclaim_during_completion(
    monkeypatch: pytest.MonkeyPatch, demo_document_cleanup: None
) -> None:
    store = MemoryStore()
    app.dependency_overrides[get_store] = lambda: store
    data = unique_sample()
    try:
        with TestClient(app) as client:
            org_id = uuid.UUID(demo_login(client)["org_id"])
            document_id = uuid.UUID(upload(client, "invoice.pdf", data)["id"])
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
                    provider = MockInvoiceProvider()
                    result, type_spec, evaluation = assess(provider, data, CONFIG)
                    complete(stale_claim, result, evaluation, type_spec, provider, CONFIG)
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
                assert json.loads(runs[0].raw_json)["document_type"] == "invoice"
    finally:
        del app.dependency_overrides[get_store]


@postgres
def test_failed_document_can_be_retried_without_reuploading(
    monkeypatch: pytest.MonkeyPatch, demo_document_cleanup: None
) -> None:
    monkeypatch.setattr("app.worker.get_provider", MockInvoiceProvider)
    store = MemoryStore()
    app.dependency_overrides[get_store] = lambda: store
    data = unique_sample()
    try:
        with TestClient(app) as client:
            org_id = uuid.UUID(demo_login(client)["org_id"])
            document_id = uuid.UUID(upload(client, "retry.pdf", data)["id"])
            claim = claim_next(org_id, document_id)
            assert claim is not None
            fail(claim, "Provider temporarily unavailable", retryable=False)
            assert client.get(f"/v1/documents/{document_id}").json()["status"] == "failed"

            duplicate = upload(client, "retry.pdf", data)
            assert duplicate["duplicate"] is True
            assert duplicate["status"] == "failed"

            retried = client.post(f"/v1/documents/{document_id}/retry")
            assert retried.status_code == 202
            assert retried.json()["status"] == "queued"
            assert retried.json()["failure_reason"] is None
            assert client.post(f"/v1/documents/{document_id}/retry").status_code == 409

            assert process_one(store, document_id) is True
            detail = client.get(f"/v1/documents/{document_id}")
            assert detail.json()["status"] == "needs_review"
            assert detail.json()["fields"]

            demo_login(client, "contoso")
            assert client.post(f"/v1/documents/{document_id}/retry").status_code == 404
    finally:
        del app.dependency_overrides[get_store]


@postgres
def test_manual_retry_limit_blocks_third_request(demo_document_cleanup: None) -> None:
    store = MemoryStore()
    app.dependency_overrides[get_store] = lambda: store
    data = unique_sample()
    try:
        with TestClient(app) as client:
            org_id = uuid.UUID(demo_login(client)["org_id"])
            document_id = uuid.UUID(upload(client, "retry-limit.pdf", data)["id"])

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


def threshold_config() -> WorkflowConfigModel:
    return default_invoice_config().model_copy(update={"review_policy": "threshold"})


def audit_events(org_id: uuid.UUID, document_id: uuid.UUID) -> list[tuple[str, dict[str, Any]]]:
    with SessionLocal() as session:
        set_org_context(session, org_id)
        rows = session.scalars(
            select(AuditEvent)
            .where(AuditEvent.org_id == org_id, AuditEvent.document_id == document_id)
            .order_by(AuditEvent.created_at, AuditEvent.id)
        )
        return [(row.event_type, json.loads(row.detail_json)) for row in rows]


@postgres
def test_threshold_policy_auto_approves_clean_documents(
    monkeypatch: pytest.MonkeyPatch, make_tenant: TenantFactory
) -> None:
    monkeypatch.setattr("app.worker.get_provider", MockInvoiceProvider)
    tenant = make_tenant(threshold_config())
    store = MemoryStore()
    app.dependency_overrides[get_store] = lambda: store
    try:
        with TestClient(app) as client:
            tenant_login(client, tenant, "member")
            document_id = uuid.UUID(upload(client, "clean.pdf", invoice_pdf())["id"])
            assert process_one(store, document_id) is True
            body = client.get(f"/v1/documents/{document_id}").json()
            assert body["status"] == "auto_approved"
            assert body["flagged_count"] == 0 and body["review_task"] is None
            assert all(field["status"] == "auto" for field in body["fields"])
            events = [event for event, _ in audit_events(tenant.org_id, document_id)]
            assert events == [
                "document.received",
                "document.queued",
                "document.extracting",
                "document.validating",
                "document.auto_approved",
            ]
            assert client.get("/v1/review/queue").json() == []
            listed = client.get("/v1/documents", params={"status": "auto_approved"}).json()
            assert [row["id"] for row in listed] == [str(document_id)]

            tenant_login(client, tenant, "reviewer")
            workspace = client.get(f"/v1/documents/{document_id}/workspace").json()
            assert workspace["capabilities"]["can_review"] is True
            assert workspace["capabilities"]["can_edit"] is False
            reopened = client.post(
                f"/v1/documents/{document_id}/review", json={"version": 0, "decision": "reopen"}
            )
            assert reopened.status_code == 200, reopened.text
            body = client.get(f"/v1/documents/{document_id}").json()
            assert body["status"] == "needs_review"
            assert body["review_task"]["outcome"] is None
            assert body["review_task"]["completed_at"] is None
            assert [row["document_id"] for row in client.get("/v1/review/queue").json()] == [
                str(document_id)
            ]
    finally:
        del app.dependency_overrides[get_store]


@postgres
def test_threshold_policy_flags_bad_fields_and_failed_rules(
    monkeypatch: pytest.MonkeyPatch, make_tenant: TenantFactory
) -> None:
    monkeypatch.setattr("app.worker.get_provider", MockInvoiceProvider)
    tenant = make_tenant(threshold_config())
    store = MemoryStore()
    app.dependency_overrides[get_store] = lambda: store
    try:
        with TestClient(app) as client:
            tenant_login(client, tenant, "admin")
            bad_date = uuid.UUID(
                upload(
                    client,
                    "bad-date.pdf",
                    invoice_pdf(invoice_number="TH-0002", invoice_date="2026-09-31"),
                )["id"]
            )
            assert process_one(store, bad_date) is True
            body = client.get(f"/v1/documents/{bad_date}").json()
            assert body["status"] == "needs_review" and body["flagged_count"] == 1
            date_field = next(field for field in body["fields"] if field["name"] == "invoice_date")
            assert date_field["status"] == "needs_review"
            assert date_field["signals"]["format"] == 0.0
            assert "Value is not a valid date" in date_field["reasons"]
            assert body["review_task"]["overdue"] is False
            flagged_event = dict(audit_events(tenant.org_id, bad_date))["document.needs_review"]
            assert flagged_event["flagged_fields"] == ["invoice_date"]
            assert flagged_event["failed_rules"] == []

            mismatch = uuid.UUID(
                upload(
                    client,
                    "mismatch.pdf",
                    invoice_pdf(
                        invoice_number="TH-0003",
                        total="$120.00",
                        extra_lines={"Subtotal": "$100.00", "Tax": "$10.00"},
                    ),
                )["id"]
            )
            assert process_one(store, mismatch) is True
            body = client.get(f"/v1/documents/{mismatch}").json()
            assert body["status"] == "needs_review"
            rules = {rule["name"]: rule for rule in body["rule_results"]}
            assert rules["totals_add_up"]["passed"] is False
            assert rules["totals_add_up"]["message"] == "Subtotal plus tax must equal total"
            assert rules["due_after_issue"]["passed"] is None
            flagged = {f["name"] for f in body["fields"] if f["status"] == "needs_review"}
            assert flagged == {"subtotal", "tax", "total"}
            assert body["flagged_count"] == 3
            flagged_event = dict(audit_events(tenant.org_id, mismatch))["document.needs_review"]
            assert flagged_event["failed_rules"] == ["totals_add_up"]
            queue = client.get("/v1/review/queue").json()
            assert [row["flagged_count"] for row in queue] == [1, 3]
    finally:
        del app.dependency_overrides[get_store]


@postgres
def test_worker_fails_documents_whose_extraction_times_out(
    monkeypatch: pytest.MonkeyPatch, make_tenant: TenantFactory
) -> None:
    class SlowProvider(MockInvoiceProvider):
        def extract(self, data: bytes, config: WorkflowConfigModel) -> ExtractionResult:
            time.sleep(2)
            return super().extract(data, config)

    monkeypatch.setattr("app.worker.get_provider", SlowProvider)
    monkeypatch.setattr(
        "app.worker.get_settings", lambda: SimpleNamespace(extraction_timeout_seconds=0.2)
    )
    tenant = make_tenant()
    store = MemoryStore()
    app.dependency_overrides[get_store] = lambda: store
    try:
        with TestClient(app) as client:
            tenant_login(client, tenant, "member")
            document_id = uuid.UUID(upload(client, "slow.pdf", invoice_pdf())["id"])
            started = time.monotonic()
            assert process_one(store, document_id) is True
            assert time.monotonic() - started < 1.5
            body = client.get(f"/v1/documents/{document_id}").json()
            assert body["status"] == "failed"
            assert body["failure_reason"] == "Extraction timed out"
            assert client.post(f"/v1/documents/{document_id}/retry").status_code == 202
    finally:
        del app.dependency_overrides[get_store]


@postgres
def test_concurrent_identical_uploads_create_one_document(make_tenant: TenantFactory) -> None:
    tenant = make_tenant()
    store = MemoryStore()
    app.dependency_overrides[get_store] = lambda: store
    data = invoice_pdf(invoice_number=f"RACE-{uuid.uuid4().hex[:8]}")
    barrier = threading.Barrier(2)

    def race() -> dict[str, Any]:
        with TestClient(app) as client:
            tenant_login(client, tenant, "member")
            barrier.wait(timeout=5)
            return upload(client, "race.pdf", data)

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(race) for _ in range(2)]
            results = [future.result(timeout=20) for future in futures]
        assert sorted(result["duplicate"] for result in results) == [False, True]
        assert len({result["id"] for result in results}) == 1
        with SessionLocal() as session:
            set_org_context(session, tenant.org_id)
            count = session.scalar(
                select(func.count())
                .select_from(Document)
                .where(
                    Document.org_id == tenant.org_id,
                    Document.content_hash == hashlib.sha256(data).hexdigest(),
                )
            )
            assert count == 1
        assert len(store.objects) == 1
    finally:
        del app.dependency_overrides[get_store]


def test_stale_lease_always_exceeds_the_extraction_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    for timeout, expected in ((60, 300), (240, 300), (600, 660)):
        settings = SimpleNamespace(extraction_timeout_seconds=timeout)
        monkeypatch.setattr("app.worker.get_settings", lambda settings=settings: settings)
        assert stale_lease_seconds() == expected


@postgres
def test_worker_retries_when_parse_slots_are_exhausted(
    monkeypatch: pytest.MonkeyPatch, make_tenant: TenantFactory
) -> None:
    monkeypatch.setattr("app.worker.get_provider", MockInvoiceProvider)
    tenant = make_tenant()
    store = MemoryStore()
    app.dependency_overrides[get_store] = lambda: store
    try:
        with TestClient(app) as client:
            tenant_login(client, tenant, "member")
            document_id = uuid.UUID(upload(client, "busy.pdf", invoice_pdf())["id"])
            exhausted = threading.BoundedSemaphore(1)
            assert exhausted.acquire(blocking=False)
            monkeypatch.setattr("app.timeouts._slots", exhausted)
            assert process_one(store, document_id) is True
            body = client.get(f"/v1/documents/{document_id}").json()
            assert body["status"] == "queued" and body["failure_reason"] is None
            events = [event for event, _ in audit_events(tenant.org_id, document_id)]
            assert events[-1] == "document.retry_scheduled"
            exhausted.release()
            # The retry backs off by two seconds before it can be claimed again.
            deadline = time.monotonic() + 8
            while not process_one(store, document_id):
                assert time.monotonic() < deadline, "retry never became claimable"
                time.sleep(0.25)
            assert client.get(f"/v1/documents/{document_id}").json()["status"] == "needs_review"
    finally:
        del app.dependency_overrides[get_store]


@postgres
def test_review_flow_end_to_end_with_corrections(
    monkeypatch: pytest.MonkeyPatch, make_tenant: TenantFactory
) -> None:
    monkeypatch.setattr("app.worker.get_provider", MockInvoiceProvider)
    tenant, bystander = make_tenant(), make_tenant()
    store = MemoryStore()
    app.dependency_overrides[get_store] = lambda: store
    try:
        with TestClient(app) as client:
            tenant_login(client, tenant, "member")
            document_id = uuid.UUID(
                upload(
                    client,
                    "flow.pdf",
                    invoice_pdf(
                        invoice_number="FLOW-0001",
                        total="$110.00",
                        extra_lines={"Subtotal": "$100.00", "Tax": "$10.00"},
                    ),
                )["id"]
            )
            assert process_one(store, document_id) is True
            tenant_login(client, tenant, "reviewer")
            path = f"/v1/documents/{document_id}"
            detail = client.get(path).json()
            assert detail["status"] == "needs_review" and detail["version"] == 0
            fields = {field["name"]: field for field in detail["fields"]}
            edited = client.post(
                f"{path}/fields/{fields['vendor']['id']}",
                json={"version": 0, "action": "edit", "value": "Northwind Traders Ltd"},
            )
            assert edited.status_code == 200, edited.text
            accepted = client.post(
                f"{path}/fields/{fields['total']['id']}", json={"version": 1, "action": "accept"}
            )
            assert accepted.status_code == 200, accepted.text
            assert accepted.json()["version"] == 2
            approved = client.post(f"{path}/review", json={"version": 2, "decision": "approve"})
            assert approved.status_code == 200, approved.text
            workspace = approved.json()
            assert workspace["verified_amount"] == "110.0000"
            assert workspace["currency"] == "USD"
            assert workspace["verified_source"] == "derived"

            # The application role sees the corrections only inside the owning tenant.
            with SessionLocal() as session:
                set_org_context(session, tenant.org_id)
                rows = session.scalars(
                    select(FieldCorrection)
                    .where(FieldCorrection.document_id == document_id)
                    .order_by(FieldCorrection.created_at, FieldCorrection.id)
                ).all()
                assert [(row.kind, row.field_name, row.after_value) for row in rows] == [
                    ("edit", "vendor", "Northwind Traders Ltd"),
                    ("accept", "total", "$110.00"),
                ]
                assert all(row.reviewer_user_id == tenant.users["reviewer"] for row in rows)
                task = session.get(ReviewTask, document_id)
                assert task is not None and task.outcome == "approved"
                assert task.completed_at is not None
            with SessionLocal() as session:
                set_org_context(session, bystander.org_id)
                assert (
                    session.scalars(
                        select(FieldCorrection).where(FieldCorrection.document_id == document_id)
                    ).all()
                    == []
                )
                assert session.get(ReviewTask, document_id) is None

            timeline = client.get(f"{path}/timeline").json()
            assert [entry["event_type"] for entry in timeline] == [
                "document.received",
                "document.queued",
                "document.extracting",
                "document.validating",
                "extraction.completed",
                "document.needs_review",
                "field.edit",
                "field.accept",
                "review.approve",
            ]
            stamps = [entry["at"] for entry in timeline]
            assert stamps == sorted(stamps)
            assert timeline[4]["detail"]["rule_results"][0]["passed"] is True
            approve_audit = dict(audit_events(tenant.org_id, document_id))["invoice.approve"]
            assert approve_audit["derived_money"] is True
            assert approve_audit["failed_rules"] == []
    finally:
        del app.dependency_overrides[get_store]
