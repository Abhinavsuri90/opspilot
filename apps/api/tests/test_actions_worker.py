"""Worker-side governance on Postgres: leases, the kill switch gate, shadow mode, retries."""

import json
import threading
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from scripts.generate_demo_invoice import invoice_pdf
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError, OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app import actions_service
from app.action_models import Action, ActionAttempt, ConnectorInstance, OrgSettings
from app.connectors.base import ActionRequest, ConnectionTest, Diff, ExecutionResult
from app.connectors.credentials import encrypt_credentials
from app.connectors.csv_export import CsvExportConnector
from app.connectors.webhook import WebhookConfig, WebhookCredentials
from app.db import SessionLocal, engine, set_org_context
from app.llm.provider import MockInvoiceProvider
from app.main import app
from app.models import AuditEvent, Document, ExtractedField, ExtractionRun, OutboxEvent
from app.storage import StoredObjectMissing, get_store
from app.worker import process_one
from app.workflow_config import DestinationSpec, WorkflowConfigModel, default_invoice_config
from tests.conftest import Tenant, TenantFactory, owner_engine, postgres
from tests.test_documents import tenant_login, upload

pytestmark = postgres


class MemoryStore:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put(self, key: str, data: bytes) -> None:
        self.objects[key] = data

    def get(self, key: str) -> bytes:
        if key not in self.objects:
            raise StoredObjectMissing(key)
        return self.objects[key]


class FakeWebhook:
    """Stands in for the webhook connector so no HTTP happens; records every execute call."""

    type_name = "webhook"
    config_model = WebhookConfig
    credentials_model: Any = WebhookCredentials

    def __init__(self) -> None:
        self.calls: list[tuple[dict[str, Any], dict[str, Any] | None, ActionRequest, str]] = []
        self.results: list[ExecutionResult] = []

    def describe_capabilities(self) -> dict[str, Any]:
        return {"action_types": ["post_webhook"]}

    def test_connection(
        self, config: dict[str, Any], credentials: dict[str, Any] | None
    ) -> ConnectionTest:
        return ConnectionTest(True, "ok")

    def preview(self, config: dict[str, Any], request: ActionRequest) -> Diff:
        return Diff("post_webhook", f"POST {config['url']}", None, dict(request.values), ["fake"])

    def execute(
        self,
        config: dict[str, Any],
        credentials: dict[str, Any] | None,
        request: ActionRequest,
        idempotency_key: str,
    ) -> ExecutionResult:
        self.calls.append((config, credentials, request, idempotency_key))
        if self.results:
            return self.results.pop(0)
        return ExecutionResult(
            True, "evt_1", "HTTP 200 (application/json, 12 bytes)", retryable=False
        )


def worker_config(*, hook_policy: str = "auto") -> WorkflowConfigModel:
    invoice = default_invoice_config().document_types[0]
    return WorkflowConfigModel(
        document_types=[invoice],
        review_policy="threshold",
        action_policies={"post_webhook": hook_policy},
        destinations=[
            DestinationSpec(
                name="hook",
                connector="hook",
                action_type="post_webhook",
                mapping={"vendor": "vendor", "total": "total", "file": "${document.filename}"},
            ),
            DestinationSpec(
                name="archive",
                connector="archive",
                action_type="export_csv",
                mapping={"vendor": "vendor", "invoice_number": "invoice_number", "total": "total"},
            ),
        ],
    )


def add_connectors(tenant: Tenant) -> dict[str, uuid.UUID]:
    ids = {"hook": uuid.uuid4(), "archive": uuid.uuid4()}
    now = datetime.now(UTC)
    with Session(owner_engine()) as session, session.begin():
        session.add_all(
            [
                ConnectorInstance(
                    id=ids["hook"],
                    org_id=tenant.org_id,
                    name="hook",
                    connector_type="webhook",
                    config_json=json.dumps({"url": "http://localhost:9/hook"}),
                    credentials_encrypted=encrypt_credentials({"secret": "shared-secret-value-1"}),
                    active=True,
                    version=1,
                    created_at=now,
                    updated_at=now,
                ),
                ConnectorInstance(
                    id=ids["archive"],
                    org_id=tenant.org_id,
                    name="archive",
                    connector_type="csv_export",
                    config_json=json.dumps({"file_prefix": "ap"}),
                    active=True,
                    version=1,
                    created_at=now,
                    updated_at=now,
                ),
            ]
        )
    return ids


def patch_registry(monkeypatch: pytest.MonkeyPatch, fake: FakeWebhook, store: MemoryStore) -> None:
    csv_connector = CsvExportConnector(store_factory=lambda: store)

    def resolve(kind: str) -> Any:
        if kind == "webhook":
            return fake
        if kind == "csv_export":
            return csv_connector
        raise AssertionError(kind)

    monkeypatch.setattr("app.actions_service.get_connector", resolve)
    monkeypatch.setattr("app.worker.get_connector", resolve)
    monkeypatch.setattr("app.worker.get_provider", MockInvoiceProvider)


def seed_approved_document(tenant: Tenant, filename: str = "seeded.pdf") -> uuid.UUID:
    """An approved document with fields, plus the propose_actions outbox row approval writes."""
    document_id = uuid.uuid4()
    now = datetime.now(UTC)
    with Session(owner_engine()) as session, session.begin():
        session.add(
            Document(
                id=document_id,
                org_id=tenant.org_id,
                uploaded_by=tenant.users["member"],
                filename=filename,
                content_type="application/pdf",
                size_bytes=10,
                content_hash=uuid.uuid4().hex,
                storage_key=f"{tenant.org_id}/{document_id}.pdf",
                workflow_config_version=1,
                status="approved",
            )
        )
        run = ExtractionRun(
            org_id=tenant.org_id,
            document_id=document_id,
            provider="mock",
            model="m",
            prompt_version="p",
            raw_json="{}",
        )
        session.add(run)
        session.flush()
        for name, value in (
            ("vendor", "Harbor Supply"),
            ("invoice_number", "HS-7"),
            ("total", "$110.00"),
        ):
            session.add(
                ExtractedField(
                    org_id=tenant.org_id,
                    document_id=document_id,
                    extraction_run_id=run.id,
                    name=name,
                    value=value,
                    evidence=f"{name}: {value}",
                    page_number=1,
                )
            )
        session.add(
            OutboxEvent(
                org_id=tenant.org_id,
                document_id=document_id,
                topic="propose_actions",
                payload_json="{}",
                attempts=0,
                available_at=now,
            )
        )
    return document_id


def actions_of(tenant: Tenant, document_id: uuid.UUID) -> dict[str, Action]:
    with SessionLocal() as session:
        set_org_context(session, tenant.org_id)
        rows = session.scalars(select(Action).where(Action.document_id == document_id)).all()
        return {row.destination: row for row in rows}


def document_status(tenant: Tenant, document_id: uuid.UUID) -> str:
    with SessionLocal() as session:
        set_org_context(session, tenant.org_id)
        document = session.get(Document, document_id)
        assert document is not None
        return document.status


def audit_types(tenant: Tenant, document_id: uuid.UUID) -> list[str]:
    with SessionLocal() as session:
        set_org_context(session, tenant.org_id)
        rows = session.scalars(
            select(AuditEvent.event_type)
            .where(AuditEvent.org_id == tenant.org_id, AuditEvent.document_id == document_id)
            .order_by(AuditEvent.created_at, AuditEvent.id)
        )
        return list(rows)


def release_action(tenant: Tenant, action_id: uuid.UUID) -> None:
    """Make a deferred action claimable now (skips the backoff or kill-switch wait)."""
    now = datetime.now(UTC) - timedelta(seconds=1)
    with Session(owner_engine()) as session, session.begin():
        action = session.get(Action, action_id)
        assert action is not None
        action.next_attempt_at = now
        for event in session.scalars(
            select(OutboxEvent).where(
                OutboxEvent.action_id == action_id, OutboxEvent.published_at.is_(None)
            )
        ):
            event.available_at = now


def test_auto_approved_document_flows_through_actions_to_completed(
    monkeypatch: pytest.MonkeyPatch, make_tenant: TenantFactory
) -> None:
    tenant = make_tenant(worker_config())
    connectors = add_connectors(tenant)
    fake, store = FakeWebhook(), MemoryStore()
    patch_registry(monkeypatch, fake, store)
    app.dependency_overrides[get_store] = lambda: store
    try:
        with TestClient(app) as client:
            tenant_login(client, tenant, "member")
            document_id = uuid.UUID(
                upload(client, "flow.pdf", invoice_pdf(invoice_number="FLOW-0007"))["id"]
            )
            assert process_one(store, document_id) is True  # extraction
            assert client.get(f"/v1/documents/{document_id}").json()["status"] == "auto_approved"
            assert process_one(store, document_id) is True  # propose_actions
            assert client.get(f"/v1/documents/{document_id}").json()["status"] == "actions_pending"
            tenant_login(client, tenant, "reviewer")
            rows = {row["destination"]: row for row in client.get("/v1/actions").json()}
            assert rows["hook"]["status"] == "approved" and rows["hook"]["policy_mode"] == "auto"
            assert rows["archive"]["status"] == "proposed"
            assert rows["hook"]["connector_name"] == "hook"
            assert rows["hook"]["preview"]["after"] == {
                "vendor": "Northwind Traders",
                "total": "$123.45",
                "file": "flow.pdf",
            }
            assert process_one(store, document_id) is True  # execute hook
            assert len(fake.calls) == 1
            config, credentials, request, key = fake.calls[0]
            assert config == {"url": "http://localhost:9/hook"}
            assert credentials == {"secret": "shared-secret-value-1"}
            assert request.values["vendor"] == "Northwind Traders"
            assert len(key) == 64
            hook = client.get(f"/v1/actions/{rows['hook']['id']}").json()
            assert hook["status"] == "succeeded" and hook["attempts"] == 1
            assert hook["result"]["external_id"] == "evt_1"
            assert hook["attempt_log"][0]["ok"] is True
            assert hook["attempt_log"][0]["response_summary"].startswith("HTTP 200")
            assert process_one(store, document_id) is False  # nothing claimable yet
            assert client.get(f"/v1/documents/{document_id}").json()["status"] == "actions_pending"
            approved = client.post(
                f"/v1/actions/{rows['archive']['id']}/decision",
                json={"version": 0, "decision": "approve", "comment": "Export it"},
            )
            assert approved.status_code == 200, approved.text
            assert process_one(store, document_id) is True  # execute archive
            archive = client.get(f"/v1/actions/{rows['archive']['id']}").json()
            assert archive["status"] == "succeeded"
            assert archive["result"]["external_id"].startswith(
                f"exports/{tenant.org_id}/{connectors['archive']}/"
            )
            assert client.get(f"/v1/documents/{document_id}").json()["status"] == "completed"
            listed = client.get("/v1/documents", params={"status": "completed"}).json()
            assert [row["id"] for row in listed] == [str(document_id)]
            tenant_login(client, tenant, "admin")
            exports = client.get("/v1/exports", params={"connector_id": str(connectors["archive"])})
            assert len(exports.json()) == 1
            csv = client.get(exports.json()[0]["path"])
            assert csv.status_code == 200 and "Northwind Traders" in csv.text
            timeline = client.get(f"/v1/documents/{document_id}/timeline").json()
            kinds = [(entry["kind"], entry["event_type"]) for entry in timeline]
            assert ("action", "action.proposed") in kinds
            assert ("action", "action.attempt") in kinds
            assert ("action", "action.succeeded") in kinds
            assert ("audit", "action.approved") in kinds
            assert ("audit", "document.actions_pending") in kinds
            assert ("audit", "document.completed") in kinds
            stamps = [entry["at"] for entry in timeline]
            assert stamps == sorted(stamps)
            approved_entry = next(
                entry for entry in timeline if entry["event_type"] == "action.approved"
            )
            assert approved_entry["actor_email"] == tenant.email("reviewer")
            assert len(fake.calls) == 1
    finally:
        del app.dependency_overrides[get_store]


class PausingSession(Session):
    """Pause the executor thread after it locks the action, before the gate reads the switch."""

    gate = threading.Event()
    proceed = threading.Event()

    def scalar(self, statement: Any, *args: Any, **kwargs: Any) -> Any:
        row = super().scalar(statement, *args, **kwargs)
        if (
            threading.current_thread().name == "executor"
            and isinstance(row, Action)
            and not PausingSession.gate.is_set()
        ):
            PausingSession.gate.set()
            if not PausingSession.proceed.wait(timeout=10):
                raise TimeoutError("worker test gate timed out")
        return row


def test_kill_switch_engaged_after_approval_blocks_execution(
    monkeypatch: pytest.MonkeyPatch, make_tenant: TenantFactory
) -> None:
    tenant = make_tenant(worker_config())
    add_connectors(tenant)
    fake, store = FakeWebhook(), MemoryStore()
    patch_registry(monkeypatch, fake, store)
    document_id = seed_approved_document(tenant)
    assert process_one(store, document_id) is True  # propose: hook auto-approved
    hook = actions_of(tenant, document_id)["hook"]
    assert hook.status == "approved"
    PausingSession.gate.clear()
    PausingSession.proceed.clear()
    monkeypatch.setattr(
        "app.worker.SessionLocal",
        sessionmaker(bind=engine, class_=PausingSession, expire_on_commit=False),
    )
    outcomes: list[bool] = []
    errors: list[Exception] = []

    def run() -> None:
        try:
            outcomes.append(process_one(store, document_id))
        except Exception as exc:  # pragma: no cover - surfaced by the assertion below
            errors.append(exc)

    thread = threading.Thread(target=run, name="executor")
    thread.start()
    try:
        assert PausingSession.gate.wait(timeout=10)
        with TestClient(app) as client:
            tenant_login(client, tenant, "admin")
            engaged = client.post("/v1/settings/policies", json={"version": 0, "kill_switch": True})
            assert engaged.status_code == 200, engaged.text
    finally:
        PausingSession.proceed.set()
        thread.join(timeout=15)
    assert not thread.is_alive() and not errors and outcomes == [True]
    assert fake.calls == []
    blocked = actions_of(tenant, document_id)["hook"]
    assert blocked.status == "approved" and blocked.attempts == 0
    assert blocked.next_attempt_at is not None and blocked.next_attempt_at > datetime.now(UTC)
    assert audit_types(tenant, document_id).count("action.blocked_kill_switch") == 1
    monkeypatch.setattr("app.worker.SessionLocal", SessionLocal)
    # Deferred: nothing is claimable until the recheck time, and a second block within the
    # hour does not add another audit row.
    assert process_one(store, document_id) is False
    release_action(tenant, hook.id)
    assert process_one(store, document_id) is True
    assert fake.calls == []
    assert audit_types(tenant, document_id).count("action.blocked_kill_switch") == 1
    with TestClient(app) as client:
        tenant_login(client, tenant, "admin")
        released = client.post("/v1/settings/policies", json={"version": 1, "kill_switch": False})
        assert released.status_code == 200, released.text
    release_action(tenant, hook.id)
    assert process_one(store, document_id) is True
    assert len(fake.calls) == 1
    assert actions_of(tenant, document_id)["hook"].status == "succeeded"


def test_shadow_mode_records_preview_and_never_calls_the_connector(
    monkeypatch: pytest.MonkeyPatch, make_tenant: TenantFactory
) -> None:
    tenant = make_tenant(worker_config())
    add_connectors(tenant)
    fake, store = FakeWebhook(), MemoryStore()
    patch_registry(monkeypatch, fake, store)
    with TestClient(app) as client:
        tenant_login(client, tenant, "admin")
        assert (
            client.post(
                "/v1/settings/policies", json={"version": 0, "shadow_mode": True}
            ).status_code
            == 200
        )
    document_id = seed_approved_document(tenant)
    assert process_one(store, document_id) is True  # propose
    assert process_one(store, document_id) is True  # execute -> shadowed
    hook = actions_of(tenant, document_id)["hook"]
    assert hook.status == "shadowed" and hook.executed_at is not None and hook.attempts == 0
    assert json.loads(hook.result_json or "{}") == json.loads(hook.preview_json)
    assert fake.calls == []
    assert "action.shadowed" in audit_types(tenant, document_id)
    with TestClient(app) as client:
        tenant_login(client, tenant, "reviewer")
        archive = next(
            row for row in client.get("/v1/actions").json() if row["destination"] == "archive"
        )
        client.post(
            f"/v1/actions/{archive['id']}/decision", json={"version": 0, "decision": "approve"}
        )
    assert process_one(store, document_id) is True
    assert actions_of(tenant, document_id)["archive"].status == "shadowed"
    assert store.objects == {}
    assert document_status(tenant, document_id) == "completed"


def test_policy_forbidden_at_execution_time_wins_over_earlier_approval(
    monkeypatch: pytest.MonkeyPatch, make_tenant: TenantFactory
) -> None:
    tenant = make_tenant(worker_config(hook_policy="needs_approval"))
    add_connectors(tenant)
    fake, store = FakeWebhook(), MemoryStore()
    patch_registry(monkeypatch, fake, store)
    document_id = seed_approved_document(tenant)
    assert process_one(store, document_id) is True
    hook = actions_of(tenant, document_id)["hook"]
    assert hook.status == "proposed"
    with TestClient(app) as client:
        tenant_login(client, tenant, "reviewer")
        approved = client.post(
            f"/v1/actions/{hook.id}/decision", json={"version": 0, "decision": "approve"}
        )
        assert approved.status_code == 200, approved.text
        tenant_login(client, tenant, "admin")
        forbidden = client.post(
            "/v1/settings/policies",
            json={"version": 0, "policies": {"post_webhook": "forbidden"}},
        )
        assert forbidden.status_code == 200, forbidden.text
    assert process_one(store, document_id) is True
    assert fake.calls == []
    assert actions_of(tenant, document_id)["hook"].status == "forbidden"
    assert "action.forbidden" in audit_types(tenant, document_id)


def test_retries_back_off_then_dead_letter_and_manual_retry_recovers(
    monkeypatch: pytest.MonkeyPatch, make_tenant: TenantFactory
) -> None:
    tenant = make_tenant(worker_config())
    add_connectors(tenant)
    fake, store = FakeWebhook(), MemoryStore()
    patch_registry(monkeypatch, fake, store)
    delays: list[int] = []

    def instant(attempts: int) -> float:
        delays.append(attempts)
        return 0.0

    monkeypatch.setattr(actions_service, "backoff_seconds", instant)
    fake.results = [
        ExecutionResult(False, None, "HTTP 503 (text/plain, 4 bytes)", retryable=True)
    ] * 5
    document_id = seed_approved_document(tenant)
    assert process_one(store, document_id) is True  # propose
    for _ in range(10):
        if actions_of(tenant, document_id)["hook"].status == "dead_lettered":
            break
        assert process_one(store, document_id) is True
    dead = actions_of(tenant, document_id)["hook"]
    assert dead.status == "dead_lettered" and dead.attempts == 5
    assert dead.error == "HTTP 503 (text/plain, 4 bytes)"
    assert len(fake.calls) == 5 and delays == [1, 2, 3, 4]
    events = audit_types(tenant, document_id)
    assert events.count("action.retry_scheduled") == 4
    assert events.count("action.dead_lettered") == 1
    assert document_status(tenant, document_id) == "actions_pending"
    with SessionLocal() as session:
        set_org_context(session, tenant.org_id)
        attempts = session.scalars(
            select(ActionAttempt)
            .where(ActionAttempt.action_id == dead.id)
            .order_by(ActionAttempt.attempt)
        ).all()
        assert [row.attempt for row in attempts] == [1, 2, 3, 4, 5]
        assert all(row.ok is False and row.error is not None for row in attempts)
    with TestClient(app) as client:
        tenant_login(client, tenant, "reviewer")
        listed = client.get("/v1/actions", params={"status": "dead_lettered"}).json()
        assert [row["id"] for row in listed] == [str(dead.id)]
        retried = client.post(
            f"/v1/actions/{dead.id}/retry", json={"version": listed[0]["version"]}
        )
        assert retried.status_code == 200, retried.text
        assert retried.json()["status"] == "approved" and retried.json()["attempts"] == 0
        archive = next(
            row for row in client.get("/v1/actions").json() if row["destination"] == "archive"
        )
        rejected = client.post(
            f"/v1/actions/{archive['id']}/decision",
            json={"version": 0, "decision": "reject", "comment": "No export"},
        )
        assert rejected.status_code == 200
    assert process_one(store, document_id) is True
    recovered = actions_of(tenant, document_id)["hook"]
    assert recovered.status == "succeeded" and recovered.attempts == 1
    assert len(fake.calls) == 6
    assert document_status(tenant, document_id) == "completed"
    # A terminal (non-retryable) failure is not retried automatically.
    other = seed_approved_document(tenant, "terminal.pdf")
    fake.results = [ExecutionResult(False, None, "HTTP 400 (text/plain, 4 bytes)", retryable=False)]
    assert process_one(store, other) is True
    assert process_one(store, other) is True
    failed = actions_of(tenant, other)["hook"]
    assert failed.status == "failed" and failed.attempts == 1
    assert process_one(store, other) is False


def test_execution_is_idempotent_when_the_same_action_runs_twice(
    monkeypatch: pytest.MonkeyPatch, make_tenant: TenantFactory
) -> None:
    tenant = make_tenant(worker_config())
    add_connectors(tenant)
    fake, store = FakeWebhook(), MemoryStore()
    patch_registry(monkeypatch, fake, store)
    document_id = seed_approved_document(tenant)
    assert process_one(store, document_id) is True  # propose
    with TestClient(app) as client:
        tenant_login(client, tenant, "reviewer")
        archive = next(
            row for row in client.get("/v1/actions").json() if row["destination"] == "archive"
        )
        assert (
            client.post(
                f"/v1/actions/{archive['id']}/decision", json={"version": 0, "decision": "approve"}
            ).status_code
            == 200
        )
    while process_one(store, document_id):
        pass
    archive_action = actions_of(tenant, document_id)["archive"]
    assert archive_action.status == "succeeded"
    key = json.loads(archive_action.result_json or "{}")["external_id"]
    assert store.objects[key].decode().count("\n") == 2  # header + one row
    # Simulate a worker that crashed after the external call: the attempt is replayed.
    now = datetime.now(UTC)
    with Session(owner_engine()) as session, session.begin():
        action = session.get(Action, archive_action.id)
        assert action is not None
        action.status = "approved"
        session.add(
            OutboxEvent(
                org_id=tenant.org_id,
                document_id=document_id,
                action_id=action.id,
                topic="execute_action",
                payload_json="{}",
                attempts=0,
                available_at=now,
            )
        )
    assert process_one(store, document_id) is True
    replayed = actions_of(tenant, document_id)["archive"]
    assert replayed.status == "succeeded" and replayed.attempts == 2
    assert json.loads(replayed.result_json or "{}")["duplicate"] is True
    assert store.objects[key].decode().count("\n") == 2
    # Proposing the same document again creates no new actions either.
    with Session(owner_engine()) as session, session.begin():
        session.add(
            OutboxEvent(
                org_id=tenant.org_id,
                document_id=document_id,
                topic="propose_actions",
                payload_json="{}",
                attempts=0,
                available_at=now,
            )
        )
    assert process_one(store, document_id) is True
    assert len(actions_of(tenant, document_id)) == 2


def test_governance_tables_enforce_tenant_rls_and_grants(make_tenant: TenantFactory) -> None:
    first, second = make_tenant(), make_tenant()
    add_connectors(first)
    add_connectors(second)
    with SessionLocal() as session:
        set_org_context(session, first.org_id)
        visible = session.scalars(select(ConnectorInstance)).all()
        assert visible and all(row.org_id == first.org_id for row in visible)
        assert (
            session.scalar(select(OrgSettings).where(OrgSettings.org_id == second.org_id)) is None
        )
        session.add(
            ConnectorInstance(
                org_id=second.org_id,
                name="intruder",
                connector_type="csv_export",
                config_json="{}",
                active=True,
                version=1,
            )
        )
        with pytest.raises(DBAPIError):
            session.flush()
        session.rollback()
        for statement in (
            "DELETE FROM actions WHERE org_id = :org",
            "DELETE FROM action_attempts WHERE org_id = :org",
            "UPDATE action_attempts SET ok = true WHERE org_id = :org",
            "DELETE FROM connector_instances WHERE org_id = :org",
        ):
            set_org_context(session, first.org_id)
            with pytest.raises(DBAPIError):
                session.execute(text(statement), {"org": first.org_id})
            session.rollback()


def test_policy_tightened_after_auto_approval_requires_a_human(
    monkeypatch: pytest.MonkeyPatch, make_tenant: TenantFactory
) -> None:
    tenant = make_tenant(worker_config())
    add_connectors(tenant)
    fake, store = FakeWebhook(), MemoryStore()
    patch_registry(monkeypatch, fake, store)
    document_id = seed_approved_document(tenant)
    assert process_one(store, document_id) is True  # propose: hook auto-approved
    assert actions_of(tenant, document_id)["hook"].status == "approved"
    with TestClient(app) as client:
        tenant_login(client, tenant, "admin")
        tightened = client.post(
            "/v1/settings/policies",
            json={"version": 0, "policies": {"post_webhook": "needs_approval"}},
        )
        assert tightened.status_code == 200, tightened.text
    assert process_one(store, document_id) is True
    hook = actions_of(tenant, document_id)["hook"]
    assert hook.status == "proposed" and hook.policy_mode == "needs_approval"
    assert hook.attempts == 0 and fake.calls == []
    assert "action.needs_approval" in audit_types(tenant, document_id)
    assert document_status(tenant, document_id) == "actions_pending"
    assert process_one(store, document_id) is False
    with TestClient(app) as client:
        tenant_login(client, tenant, "reviewer")
        approved = client.post(
            f"/v1/actions/{hook.id}/decision", json={"version": hook.version, "decision": "approve"}
        )
        assert approved.status_code == 200, approved.text
    assert process_one(store, document_id) is True
    assert actions_of(tenant, document_id)["hook"].status == "succeeded"
    assert len(fake.calls) == 1


def test_busy_worker_defers_the_attempt_without_spending_budget(
    monkeypatch: pytest.MonkeyPatch, make_tenant: TenantFactory
) -> None:
    tenant = make_tenant(worker_config())
    add_connectors(tenant)
    fake, store = FakeWebhook(), MemoryStore()
    patch_registry(monkeypatch, fake, store)
    document_id = seed_approved_document(tenant)
    assert process_one(store, document_id) is True  # propose
    exhausted = threading.BoundedSemaphore(1)
    assert exhausted.acquire(blocking=False)
    monkeypatch.setattr("app.timeouts._connector_slots", exhausted)
    before = datetime.now(UTC)
    assert process_one(store, document_id) is True
    hook = actions_of(tenant, document_id)["hook"]
    assert hook.status == "approved" and hook.attempts == 0 and fake.calls == []
    assert hook.next_attempt_at is not None
    assert hook.next_attempt_at >= before + timedelta(seconds=25)
    with SessionLocal() as session:
        set_org_context(session, tenant.org_id)
        assert (
            session.scalars(select(ActionAttempt).where(ActionAttempt.action_id == hook.id)).all()
            == []
        )
    assert process_one(store, document_id) is False  # deferred, not claimable yet
    exhausted.release()
    release_action(tenant, hook.id)
    assert process_one(store, document_id) is True
    hook = actions_of(tenant, document_id)["hook"]
    assert hook.status == "succeeded" and hook.attempts == 1 and len(fake.calls) == 1
    assert audit_types(tenant, document_id).count("action.retry_scheduled") == 0


def test_poison_events_are_abandoned_after_three_claims(
    monkeypatch: pytest.MonkeyPatch, make_tenant: TenantFactory
) -> None:
    tenant = make_tenant(worker_config())
    add_connectors(tenant)
    fake, store = FakeWebhook(), MemoryStore()
    patch_registry(monkeypatch, fake, store)
    document_id = seed_approved_document(tenant)
    assert process_one(store, document_id) is True  # propose
    with Session(owner_engine()) as session, session.begin():
        for event in session.scalars(
            select(OutboxEvent).where(
                OutboxEvent.document_id == document_id, OutboxEvent.published_at.is_(None)
            )
        ):
            event.attempts = 3  # claimed three times without finishing
            event.claimed_at = None
    assert process_one(store, document_id) is True
    hook = actions_of(tenant, document_id)["hook"]
    assert hook.status == "failed" and hook.error == "worker interrupted repeatedly"
    assert fake.calls == []
    assert "action.event_abandoned" in audit_types(tenant, document_id)
    assert process_one(store, document_id) is False
    other = seed_approved_document(tenant, "poison-propose.pdf")
    with Session(owner_engine()) as session, session.begin():
        for event in session.scalars(select(OutboxEvent).where(OutboxEvent.document_id == other)):
            event.attempts = 3
    assert process_one(store, other) is True
    assert actions_of(tenant, other) == {}
    assert "action.event_abandoned" in audit_types(tenant, other)
    assert process_one(store, other) is False


def test_outcome_recording_retries_transient_database_errors(
    monkeypatch: pytest.MonkeyPatch, make_tenant: TenantFactory
) -> None:
    tenant = make_tenant(worker_config())
    add_connectors(tenant)
    fake, store = FakeWebhook(), MemoryStore()
    patch_registry(monkeypatch, fake, store)
    real = actions_service.finish_attempt
    calls: list[int] = []

    def flaky(*args: Any, **kwargs: Any) -> None:
        calls.append(1)
        if len(calls) == 1:
            raise OperationalError("UPDATE actions", {}, Exception("connection reset"))
        real(*args, **kwargs)

    monkeypatch.setattr(actions_service, "finish_attempt", flaky)
    monkeypatch.setattr("app.worker.FINISH_RETRY_DELAY_SECONDS", 0)
    document_id = seed_approved_document(tenant)
    assert process_one(store, document_id) is True  # propose
    assert process_one(store, document_id) is True  # execute, first recording fails
    hook = actions_of(tenant, document_id)["hook"]
    assert hook.status == "succeeded" and hook.attempts == 1
    assert len(fake.calls) == 1 and len(calls) == 2
    with SessionLocal() as session:
        set_org_context(session, tenant.org_id)
        attempts = session.scalars(
            select(ActionAttempt).where(ActionAttempt.action_id == hook.id)
        ).all()
        assert len(attempts) == 1 and attempts[0].ok is True


def test_second_worker_skips_an_event_another_worker_holds(
    monkeypatch: pytest.MonkeyPatch, make_tenant: TenantFactory
) -> None:
    tenant = make_tenant(worker_config())
    add_connectors(tenant)
    fake, store = FakeWebhook(), MemoryStore()
    patch_registry(monkeypatch, fake, store)
    document_id = seed_approved_document(tenant)
    assert process_one(store, document_id) is True  # propose
    PausingSession.gate.clear()
    PausingSession.proceed.clear()
    monkeypatch.setattr(
        "app.worker.SessionLocal",
        sessionmaker(bind=engine, class_=PausingSession, expire_on_commit=False),
    )
    outcomes: list[bool] = []
    errors: list[Exception] = []

    def run() -> None:
        try:
            outcomes.append(process_one(store, document_id))
        except Exception as exc:  # pragma: no cover - surfaced by the assertion below
            errors.append(exc)

    thread = threading.Thread(target=run, name="executor")
    thread.start()
    try:
        assert PausingSession.gate.wait(timeout=10)
        # The first worker holds the outbox row; SKIP LOCKED makes the second find nothing.
        assert process_one(store, document_id) is False
        assert fake.calls == []
    finally:
        PausingSession.proceed.set()
        thread.join(timeout=15)
    assert not thread.is_alive() and not errors and outcomes == [True]
    assert len(fake.calls) == 1
    assert actions_of(tenant, document_id)["hook"].status == "succeeded"
    assert process_one(store, document_id) is False


def test_action_attempts_cannot_reference_another_tenants_action(
    make_tenant: TenantFactory,
) -> None:
    first, second = make_tenant(), make_tenant()
    document_id = seed_approved_document(first)
    action_id = uuid.uuid4()
    with Session(owner_engine()) as session, session.begin():
        session.add(
            Action(
                id=action_id,
                org_id=first.org_id,
                document_id=document_id,
                action_type="post_webhook",
                destination="hook",
                payload_json="{}",
                preview_json="{}",
                status="proposed",
                policy_mode="needs_approval",
                idempotency_key=uuid.uuid4().hex,
                attempts=0,
                version=0,
            )
        )
    with Session(owner_engine()) as session:
        session.add(ActionAttempt(org_id=second.org_id, action_id=action_id, attempt=1, ok=False))
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()
        session.add(ActionAttempt(org_id=first.org_id, action_id=action_id, attempt=1, ok=False))
        session.flush()
        session.rollback()
