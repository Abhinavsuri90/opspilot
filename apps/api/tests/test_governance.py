"""Settings, connectors, workflow versions, proposals and the actions API over SQLite."""

import json
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, event, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import actions_service, settings_service
from app.action_models import Action, ConnectorInstance, OrgActionPolicy, OrgSettings
from app.auth import current_session
from app.connectors.base import ActionRequest, ConnectionTest, Diff, ExecutionResult
from app.connectors.credentials import decrypt_credentials, encrypt_credentials
from app.connectors.csv_export import export_key
from app.main import app
from app.models import (
    AuditEvent,
    Base,
    Document,
    ExtractedField,
    ExtractionRun,
    Membership,
    Organization,
    OutboxEvent,
    User,
    WorkflowConfig,
)
from app.storage import StoredObjectMissing, get_store
from app.workflow_config import DestinationSpec, WorkflowConfigModel, default_invoice_config
from app.workflow_models import FieldCorrection, InvoiceMetadata

NOW = datetime.now(UTC).replace(microsecond=0)
SECRET = "webhook-shared-secret-1"


def governance_config() -> WorkflowConfigModel:
    invoice = default_invoice_config().document_types[0]
    return WorkflowConfigModel(
        document_types=[invoice],
        action_policies={"post_webhook": "auto", "create_record": "forbidden"},
        destinations=[
            DestinationSpec(
                name="hook",
                connector="hook",
                action_type="post_webhook",
                mapping={
                    "vendor": "vendor",
                    "amount": "${verified.amount}",
                    "currency": "${verified.currency}",
                    "file": "${document.filename}",
                },
            ),
            DestinationSpec(
                name="archive",
                connector="archive",
                action_type="export_csv",
                mapping={"vendor": "vendor", "invoice_number": "invoice_number", "total": "total"},
            ),
            DestinationSpec(
                name="ledger",
                connector="ledger",
                action_type="create_record",
                mapping={"vendor": "vendor", "total": "total"},
            ),
            DestinationSpec(
                name="ghost",
                connector="missing",
                action_type="post_webhook",
                mapping={"vendor": "vendor"},
            ),
        ],
    )


class MemoryStore:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put(self, key: str, data: bytes) -> None:
        self.objects[key] = data

    def get(self, key: str) -> bytes:
        if key not in self.objects:
            raise StoredObjectMissing(key)
        return self.objects[key]


@dataclass
class Gov:
    client: TestClient
    engine: Engine
    actors: dict[str, uuid.UUID]
    org_id: uuid.UUID
    other_org_id: uuid.UUID
    document_id: uuid.UUID
    other_document_id: uuid.UUID
    connectors: dict[str, uuid.UUID]
    store: MemoryStore
    actor: str = "admin"

    def propose(self, document_id: uuid.UUID | None = None) -> list[Action]:
        with Session(self.engine, expire_on_commit=False) as session, session.begin():
            document = session.get(Document, document_id or self.document_id)
            assert document is not None
            row = session.scalar(
                select(WorkflowConfig).where(WorkflowConfig.org_id == document.org_id)
            )
            assert row is not None
            config = WorkflowConfigModel.model_validate_json(row.config_json)
            return actions_service.propose_for_document(session, document, config, NOW).created

    def actions(self, **params: object) -> list[dict[str, Any]]:
        response = self.client.get("/v1/actions", params=params)
        assert response.status_code == 200, response.text
        return list(response.json())

    def by_destination(self, **params: object) -> dict[str, dict[str, Any]]:
        return {row["destination"]: row for row in self.actions(**params)}

    def audits(self, event_type: str) -> list[dict[str, Any]]:
        with Session(self.engine) as session:
            rows = session.scalars(
                select(AuditEvent)
                .where(AuditEvent.org_id == self.org_id, AuditEvent.event_type == event_type)
                .order_by(AuditEvent.created_at, AuditEvent.id)
            )
            return [json.loads(row.detail_json) for row in rows]


def make_document(org_id: uuid.UUID, user_id: uuid.UUID, filename: str, status: str) -> Document:
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
        created_at=NOW - timedelta(hours=1),
        updated_at=NOW - timedelta(hours=1),
    )


def add_fields(
    session: Session, document: Document, values: dict[str, str]
) -> dict[str, uuid.UUID]:
    run = ExtractionRun(
        org_id=document.org_id,
        document_id=document.id,
        provider="mock",
        model="invoice-pattern-v2",
        prompt_version="mock-v2",
        raw_json="{}",
        created_at=NOW - timedelta(minutes=50),
    )
    session.add(run)
    session.flush()
    ids = {}
    for name, value in values.items():
        field = ExtractedField(
            org_id=document.org_id,
            document_id=document.id,
            extraction_run_id=run.id,
            name=name,
            value=value,
            evidence=f"{name}: {value}",
            page_number=1,
        )
        session.add(field)
        session.flush()
        ids[name] = field.id
    return ids


@pytest.fixture
def gov() -> Iterator[Gov]:
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
    names = ("admin", "reviewer", "member", "viewer", "external")
    actors = {name: uuid.uuid4() for name in names}
    connectors: dict[str, uuid.UUID] = {}
    with Session(engine) as session:
        session.add_all(
            [
                Organization(id=org_id, slug="gov", name="Governed", default_currency="USD"),
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
        for target in (org_id, other_org):
            session.add(
                WorkflowConfig(
                    org_id=target, version=1, config_json=governance_config().model_dump_json()
                )
            )
        for target, name, kind, config, credentials in (
            (org_id, "hook", "webhook", {"url": "http://localhost:9/hook"}, {"secret": SECRET}),
            (org_id, "archive", "csv_export", {"file_prefix": "ap"}, None),
            (
                org_id,
                "ledger",
                "postgres_table",
                {"schema": "public", "table": "ap_ledger"},
                {"dsn": "postgresql://u:p@db.example.test:5432/ledger"},
            ),
            (other_org, "hook", "webhook", {"url": "http://localhost:9/other"}, {"secret": SECRET}),
        ):
            row = ConnectorInstance(
                id=uuid.uuid4(),
                org_id=target,
                name=name,
                connector_type=kind,
                config_json=json.dumps(config),
                credentials_encrypted=encrypt_credentials(credentials) if credentials else None,
                active=True,
                version=1,
                created_at=NOW,
                updated_at=NOW,
            )
            session.add(row)
            if target == org_id:
                connectors[name] = row.id
        document = make_document(org_id, actors["member"], "harbor-supply.pdf", "approved")
        other = make_document(other_org, actors["external"], "outside.pdf", "approved")
        session.add_all([document, other])
        session.flush()
        field_ids = add_fields(
            session,
            document,
            {
                "vendor": "Harbor Supply",
                "invoice_number": "HS-1001",
                "total": "$110.00",
                "currency": "USD",
            },
        )
        add_fields(session, other, {"vendor": "Outside", "total": "$1.00"})
        session.add(
            FieldCorrection(
                org_id=org_id,
                document_id=document.id,
                field_id=field_ids["vendor"],
                field_name="vendor",
                kind="edit",
                before_value="Harbor Supply",
                after_value="Harbor Supply Ltd",
                reviewer_user_id=actors["reviewer"],
                created_at=NOW - timedelta(minutes=30),
            )
        )
        session.add(
            InvoiceMetadata(
                document_id=document.id,
                org_id=org_id,
                verified_amount=Decimal("110.0000"),
                currency="USD",
                verified_source="derived",
                version=1,
            )
        )
        session.commit()
        ids = (document.id, other.id)

    store = MemoryStore()
    with TestClient(app) as client:
        state = Gov(client, engine, actors, org_id, other_org, *ids, connectors, store)

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
        app.dependency_overrides[get_store] = lambda: store
        try:
            yield state
        finally:
            app.dependency_overrides.pop(current_session, None)
            app.dependency_overrides.pop(get_store, None)
    engine.dispose()


# Policies and switches


def test_policies_defaults_updates_audits_and_isolation(gov: Gov) -> None:
    client = gov.client
    initial = client.get("/v1/settings/policies")
    assert initial.status_code == 200, initial.text
    assert initial.json() == {
        "version": 0,
        "kill_switch": False,
        "shadow_mode": False,
        "daily_llm_spend_cap_cents": None,
        "policies": {},
        "defaults_from_config": {"post_webhook": "auto", "create_record": "forbidden"},
        "known_action_types": ["append_row", "create_record", "post_webhook", "export_csv"],
        "updated_at": initial.json()["updated_at"],
        "updated_by_email": None,
    }
    changed = client.post(
        "/v1/settings/policies",
        json={
            "version": 0,
            "kill_switch": True,
            "shadow_mode": True,
            "policies": {"post_webhook": "needs_approval", "export_csv": "auto"},
        },
    )
    assert changed.status_code == 200, changed.text
    body = changed.json()
    assert body["version"] == 1 and body["kill_switch"] and body["shadow_mode"]
    assert body["policies"] == {"export_csv": "auto", "post_webhook": "needs_approval"}
    assert body["updated_by_email"] == "admin@example.com"
    assert (
        client.post("/v1/settings/policies", json={"version": 0, "kill_switch": False}).status_code
        == 409
    )
    assert (
        client.post(
            "/v1/settings/policies", json={"version": 1, "policies": {"send_email": "auto"}}
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/v1/settings/policies", json={"version": 1, "policies": {"export_csv": "maybe"}}
        ).status_code
        == 422
    )
    # Re-saving the same values bumps the version without new audit rows.
    same = client.post(
        "/v1/settings/policies",
        json={"version": 1, "kill_switch": True, "policies": {"export_csv": "auto"}},
    )
    assert same.status_code == 200 and same.json()["version"] == 2
    released = client.post("/v1/settings/policies", json={"version": 2, "kill_switch": False})
    assert released.status_code == 200 and released.json()["kill_switch"] is False
    assert [event["kill_switch"] for event in gov.audits("settings.kill_switch_enabled")] == [True]
    assert [event["kill_switch"] for event in gov.audits("settings.kill_switch_disabled")] == [
        False
    ]
    assert gov.audits("settings.shadow_mode_changed") == [{"shadow_mode": True}]
    assert gov.audits("settings.policy_changed") == [
        {"action_type": "post_webhook", "from": None, "to": "needs_approval"},
        {"action_type": "export_csv", "from": None, "to": "auto"},
    ]
    with Session(gov.engine) as session:
        settings = session.get(OrgSettings, gov.org_id)
        assert settings is not None and settings.version == 3
        policies = session.scalars(select(OrgActionPolicy)).all()
        assert {(row.org_id, row.action_type) for row in policies} == {
            (gov.org_id, "post_webhook"),
            (gov.org_id, "export_csv"),
        }
    for actor in ("reviewer", "member", "viewer"):
        gov.actor = actor
        assert client.get("/v1/settings/policies").status_code == 403
        assert client.post("/v1/settings/policies", json={"version": 3}).status_code == 403
    gov.actor = "external"
    other = client.get("/v1/settings/policies").json()
    assert other["version"] == 0 and other["policies"] == {} and other["kill_switch"] is False


# Connectors


def test_connectors_crud_validation_and_secrecy(gov: Gov) -> None:
    client = gov.client
    listed = client.get("/v1/settings/connectors")
    assert listed.status_code == 200, listed.text
    assert [row["name"] for row in listed.json()] == ["archive", "hook", "ledger"]
    assert SECRET not in listed.text and "dsn" not in listed.text
    hook = next(row for row in listed.json() if row["name"] == "hook")
    assert hook["has_credentials"] is True and hook["config"] == {"url": "http://localhost:9/hook"}
    assert hook["capabilities"]["action_types"] == ["post_webhook"]
    assert hook["last_test_at"] is None and hook["active"] is True and hook["version"] == 1

    created = client.post(
        "/v1/settings/connectors",
        json={
            "name": "second-hook",
            "connector_type": "webhook",
            "config": {"url": "http://localhost:9/second", "headers": {"X-Tenant": "gov"}},
            "credentials": {"secret": "another-shared-secret"},
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["has_credentials"] is True
    assert "another-shared-secret" not in created.text
    connector_id = created.json()["id"]
    with Session(gov.engine) as session:
        row = session.get(ConnectorInstance, uuid.UUID(connector_id))
        assert row is not None and row.credentials_encrypted is not None
        assert "another-shared-secret" not in row.credentials_encrypted
        assert decrypt_credentials(row.credentials_encrypted) == {"secret": "another-shared-secret"}

    duplicate = client.post(
        "/v1/settings/connectors",
        json={
            "name": "hook",
            "connector_type": "webhook",
            "config": {"url": "http://localhost:9/x"},
            "credentials": {"secret": "another-shared-secret"},
        },
    )
    assert duplicate.status_code == 409
    for payload, fragment in (
        ({"name": "bad", "connector_type": "webhook", "config": {}}, "config.url"),
        (
            {"name": "bad", "connector_type": "webhook", "config": {"url": "http://localhost:9/x"}},
            "require credentials",
        ),
        (
            {
                "name": "bad",
                "connector_type": "webhook",
                "config": {"url": "http://localhost:9/x"},
                "credentials": {"secret": "short"},
            },
            "credentials.secret",
        ),
        (
            {
                "name": "bad",
                "connector_type": "csv_export",
                "config": {},
                "credentials": {"secret": "x" * 20},
            },
            "do not take credentials",
        ),
        (
            {"name": "bad", "connector_type": "postgres_table", "config": {"schema": "p"}},
            "config.table",
        ),
        (
            {
                "name": "bad",
                "connector_type": "google_sheets",
                "config": {"spreadsheet_id": "sheet_1234567890", "sheet_name": "L"},
                "credentials": {"service_account_json": "{}"},
            },
            "client_email",
        ),
    ):
        response = client.post("/v1/settings/connectors", json=payload)
        assert response.status_code == 422, response.text
        assert fragment in response.json()["error"]["message"], payload
    assert (
        client.post(
            "/v1/settings/connectors",
            json={"name": "x", "connector_type": "browser", "config": {}},
        ).status_code
        == 422
    )

    renamed = client.post(
        f"/v1/settings/connectors/{connector_id}",
        json={"version": 1, "name": "renamed-hook", "active": False},
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["name"] == "renamed-hook" and renamed.json()["active"] is False
    assert renamed.json()["version"] == 2
    assert (
        client.post(
            f"/v1/settings/connectors/{connector_id}", json={"version": 1, "active": True}
        ).status_code
        == 409
    )
    assert (
        client.post(
            f"/v1/settings/connectors/{connector_id}", json={"version": 2, "name": "hook"}
        ).status_code
        == 409
    )
    rotated = client.post(
        f"/v1/settings/connectors/{connector_id}",
        json={"version": 2, "credentials": {"secret": "rotated-shared-secret"}},
    )
    assert rotated.status_code == 200 and rotated.json()["version"] == 3
    with Session(gov.engine) as session:
        row = session.get(ConnectorInstance, uuid.UUID(connector_id))
        assert row is not None and row.credentials_encrypted is not None
        assert decrypt_credentials(row.credentials_encrypted) == {"secret": "rotated-shared-secret"}
    assert (
        client.post(
            f"/v1/settings/connectors/{uuid.uuid4()}", json={"version": 1, "active": True}
        ).status_code
        == 404
    )
    audit_types = [event["connector_id"] for event in gov.audits("connector.updated")]
    assert audit_types == [connector_id] * 2
    for actor in ("reviewer", "member", "viewer"):
        gov.actor = actor
        assert client.get("/v1/settings/connectors").status_code == 403
        assert (
            client.post(
                "/v1/settings/connectors", json={"name": "x", "connector_type": "csv_export"}
            ).status_code
            == 403
        )
    gov.actor = "external"
    assert [row["name"] for row in client.get("/v1/settings/connectors").json()] == ["hook"]
    assert (
        client.post(
            f"/v1/settings/connectors/{connector_id}", json={"version": 3, "active": True}
        ).status_code
        == 404
    )
    assert client.post(f"/v1/settings/connectors/{connector_id}/test").status_code == 404


class FakeConnector:
    type_name = "webhook"

    def __init__(self, outcome: ConnectionTest | None = None, slow: bool = False) -> None:
        self.outcome = outcome or ConnectionTest(True, "HTTP 200")
        self.slow = slow
        self.calls: list[tuple[dict[str, Any], dict[str, Any] | None]] = []

    @property
    def config_model(self) -> Any:
        from app.connectors.webhook import WebhookConfig

        return WebhookConfig

    @property
    def credentials_model(self) -> Any:
        from app.connectors.webhook import WebhookCredentials

        return WebhookCredentials

    def describe_capabilities(self) -> dict[str, Any]:
        return {"action_types": ["post_webhook"]}

    def test_connection(
        self, config: dict[str, Any], credentials: dict[str, Any] | None
    ) -> ConnectionTest:
        self.calls.append((config, credentials))
        if self.slow:
            import time

            time.sleep(1)
        return self.outcome

    def preview(self, config: dict[str, Any], request: ActionRequest) -> Diff:
        return Diff("post_webhook", "fake", None, dict(request.values), [])

    def execute(
        self,
        config: dict[str, Any],
        credentials: dict[str, Any] | None,
        request: ActionRequest,
        idempotency_key: str,
    ) -> ExecutionResult:
        return ExecutionResult(True, None, "ok", retryable=False)


def test_connector_test_endpoint_records_outcome(gov: Gov, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeConnector(ConnectionTest(False, "HTTP 500"))
    monkeypatch.setattr(settings_service, "get_connector", lambda kind: fake)
    tested = gov.client.post(f"/v1/settings/connectors/{gov.connectors['hook']}/test")
    assert tested.status_code == 200, tested.text
    assert tested.json()["ok"] is False and tested.json()["message"] == "HTTP 500"
    assert fake.calls == [({"url": "http://localhost:9/hook"}, {"secret": SECRET})]
    listed = {row["name"]: row for row in gov.client.get("/v1/settings/connectors").json()}
    assert listed["hook"]["last_test_ok"] is False
    assert listed["hook"]["last_test_message"] == "HTTP 500"
    assert listed["hook"]["last_test_at"] is not None
    assert gov.audits("connector.tested")[-1]["ok"] is False
    monkeypatch.setattr(settings_service, "CONNECTION_TEST_TIMEOUT_SECONDS", 0.1)
    monkeypatch.setattr(settings_service, "get_connector", lambda kind: FakeConnector(slow=True))
    timed_out = gov.client.post(f"/v1/settings/connectors/{gov.connectors['hook']}/test")
    assert (
        timed_out.status_code == 200 and timed_out.json()["message"] == "Connection test timed out"
    )
    gov.actor = "reviewer"
    assert (
        gov.client.post(f"/v1/settings/connectors/{gov.connectors['hook']}/test").status_code == 403
    )


# Workflow configuration versions


def test_workflow_config_yaml_round_trip_and_validation(gov: Gov) -> None:
    client = gov.client
    current = client.get("/v1/settings/workflow")
    assert current.status_code == 200, current.text
    assert current.json()["version"] == 1
    assert current.json()["config"]["destinations"][0]["name"] == "hook"
    parsed = yaml.safe_load(current.json()["yaml"])
    assert parsed["document_types"][0]["name"] == "invoice"
    assert parsed["destinations"][1]["mapping"]["invoice_number"] == "invoice_number"
    # Drop the destination whose connector is missing and add a literal column.
    parsed["destinations"] = [item for item in parsed["destinations"] if item["name"] != "ghost"]
    parsed["destinations"][0]["mapping"]["document"] = "${document.id}"
    updated = client.post(
        "/v1/settings/workflow", json={"base_version": 1, "yaml": yaml.safe_dump(parsed)}
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["version"] == 2
    assert [item["name"] for item in updated.json()["config"]["destinations"]] == [
        "hook",
        "archive",
        "ledger",
    ]
    assert client.get("/v1/settings/workflow").json()["version"] == 2
    stale = client.post("/v1/settings/workflow", json={"base_version": 1, "config": parsed})
    assert stale.status_code == 409
    assert "version 2" in stale.json()["error"]["message"]
    with Session(gov.engine) as session:
        versions = session.scalars(
            select(WorkflowConfig.version)
            .where(WorkflowConfig.org_id == gov.org_id)
            .order_by(WorkflowConfig.version)
        ).all()
        assert versions == [1, 2]
    assert gov.audits("workflow.config_updated") == [
        {
            "version": 2,
            "base_version": 1,
            "document_types": ["invoice"],
            "destinations": ["hook", "archive", "ledger"],
        }
    ]

    broken_yaml = client.post("/v1/settings/workflow", json={"base_version": 2, "yaml": "a: [b"})
    assert broken_yaml.status_code == 422
    assert "YAML could not be parsed" in broken_yaml.json()["error"]["message"]
    scalar = client.post("/v1/settings/workflow", json={"base_version": 2, "yaml": "just text"})
    assert scalar.status_code == 422 and "mapping" in scalar.json()["error"]["message"]
    parsed["destinations"][0]["mapping"]["mystery"] = "not_a_field"
    unknown_field = client.post("/v1/settings/workflow", json={"base_version": 2, "config": parsed})
    assert unknown_field.status_code == 422
    error = unknown_field.json()["error"]
    assert error["code"] == "validation_error"
    assert error["message"] == "Workflow configuration is invalid"
    assert any("unknown field 'not_a_field'" in item["message"] for item in error["details"])
    del parsed["destinations"][0]["mapping"]["mystery"]
    parsed["destinations"].append(
        {
            "name": "nowhere",
            "connector": "missing",
            "action_type": "post_webhook",
            "mapping": {"vendor": "vendor"},
        }
    )
    missing_connector = client.post(
        "/v1/settings/workflow", json={"base_version": 2, "config": parsed}
    )
    assert missing_connector.status_code == 422
    assert "unknown connector 'missing'" in missing_connector.json()["error"]["message"]
    assert missing_connector.json()["error"]["details"][0]["field"] == (
        "destinations.nowhere.connector"
    )
    parsed["destinations"][-1] = {
        "name": "mismatch",
        "connector": "archive",
        "action_type": "post_webhook",
        "mapping": {"vendor": "vendor"},
    }
    mismatch = client.post("/v1/settings/workflow", json={"base_version": 2, "config": parsed})
    assert mismatch.status_code == 422
    assert "needs a webhook connector" in mismatch.json()["error"]["message"]
    assert (
        client.post(
            "/v1/settings/workflow", json={"base_version": 2, "config": parsed, "yaml": "x: 1"}
        ).status_code
        == 422
    )
    assert client.post("/v1/settings/workflow", json={"base_version": 2}).status_code == 422
    # The 64 KB JSON body cap stops oversized YAML at the edge; the service enforces it too.
    assert (
        client.post(
            "/v1/settings/workflow", json={"base_version": 2, "yaml": "x" * (64 * 1024 + 1)}
        ).status_code
        == 413
    )
    with pytest.raises(settings_service.SettingsInvalid, match="64 KB"):
        settings_service.parse_workflow(None, "x" * (64 * 1024 + 1))
    gov.actor = "reviewer"
    assert client.get("/v1/settings/workflow").status_code == 403
    gov.actor = "external"
    assert client.get("/v1/settings/workflow").json()["version"] == 1


# Proposals


def test_proposal_applies_policy_matrix_and_is_idempotent(gov: Gov) -> None:
    created = gov.propose()
    by_name = {action.destination: action for action in created}
    assert set(by_name) == {"hook", "archive", "ledger", "ghost"}
    assert by_name["hook"].status == "approved" and by_name["hook"].policy_mode == "auto"
    assert (
        by_name["archive"].status == "proposed"
        and by_name["archive"].policy_mode == "needs_approval"
    )
    assert by_name["ledger"].status == "forbidden" and by_name["ledger"].policy_mode == "forbidden"
    assert by_name["ghost"].status == "failed" and by_name["ghost"].error == "connector missing"
    assert by_name["ghost"].connector_id is None
    # Effective (corrected) values and metadata literals feed the payload.
    assert json.loads(by_name["hook"].payload_json) == {
        "vendor": "Harbor Supply Ltd",
        "amount": "110.0000",
        "currency": "USD",
        "file": "harbor-supply.pdf",
    }
    preview = json.loads(by_name["hook"].preview_json)
    assert preview["kind"] == "post_webhook" and preview["title"] == "POST http://localhost:9/hook"
    assert preview["after"]["payload"]["vendor"] == "Harbor Supply Ltd"
    assert len({action.idempotency_key for action in created}) == 4
    with Session(gov.engine) as session:
        document = session.get(Document, gov.document_id)
        assert document is not None and document.status == "actions_pending"
        events = session.scalars(
            select(OutboxEvent).where(OutboxEvent.document_id == gov.document_id)
        ).all()
        assert [(event.topic, event.action_id) for event in events] == [
            ("execute_action", by_name["hook"].id)
        ]
    assert [event["destination"] for event in gov.audits("action.proposed")] == [
        "hook",
        "archive",
        "ledger",
        "ghost",
    ]
    assert gov.audits("action.forbidden")[0]["destination"] == "ledger"
    assert gov.audits("action.failed")[0]["error"] == "connector missing"
    assert gov.audits("document.actions_pending")
    # The same document proposed again produces nothing new.
    assert gov.propose() == []
    with Session(gov.engine) as session:
        assert (
            len(session.scalars(select(Action).where(Action.document_id == gov.document_id)).all())
            == 4
        )
    # A tenant-side policy override beats the config default for the next proposal.
    gov.client.post(
        "/v1/settings/policies", json={"version": 0, "policies": {"post_webhook": "forbidden"}}
    )
    with Session(gov.engine) as session, session.begin():
        session.execute(
            select(Action).where(Action.document_id == gov.document_id)
        )  # keep the session generic
        fresh = make_document(gov.org_id, gov.actors["member"], "second.pdf", "approved")
        session.add(fresh)
        session.flush()
        add_fields(session, fresh, {"vendor": "Second", "invoice_number": "S-2", "total": "$5.00"})
        second_id = fresh.id
    second = {action.destination: action for action in gov.propose(second_id)}
    assert second["hook"].status == "forbidden" and second["hook"].policy_mode == "forbidden"
    with Session(gov.engine) as session:
        document = session.get(Document, second_id)
        assert document is not None and document.status == "actions_pending"


def test_actions_api_list_detail_decision_and_retry(gov: Gov) -> None:
    gov.propose()
    client = gov.client
    rows = gov.by_destination()
    assert set(rows) == {"hook", "archive", "ledger", "ghost"}
    archive = rows["archive"]
    assert archive == {
        "id": archive["id"],
        "document_id": str(gov.document_id),
        "filename": "harbor-supply.pdf",
        "destination": "archive",
        "action_type": "export_csv",
        "connector_id": str(gov.connectors["archive"]),
        "connector_name": "archive",
        "status": "proposed",
        "policy_mode": "needs_approval",
        "preview": archive["preview"],
        "attempts": 0,
        "next_attempt_at": None,
        "error": None,
        "proposed_at": archive["proposed_at"],
        "decided_by_email": None,
        "decided_at": None,
        "decision_comment": "",
        "executed_at": None,
        "version": 0,
    }
    assert archive["preview"]["kind"] == "export_csv"
    assert archive["preview"]["after"] == {
        "vendor": "Harbor Supply Ltd",
        "invoice_number": "HS-1001",
        "total": "$110.00",
    }
    assert [row["destination"] for row in gov.actions(status="proposed")] == ["archive"]
    assert gov.actions(document_id=str(uuid.uuid4())) == []
    assert client.get("/v1/actions", params={"status": "pending"}).status_code == 422
    detail = client.get(f"/v1/actions/{archive['id']}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["payload"] == archive["preview"]["after"]
    assert detail.json()["result"] is None and detail.json()["attempt_log"] == []
    assert client.get(f"/v1/actions/{uuid.uuid4()}").status_code == 404

    gov.actor = "viewer"
    assert len(gov.actions()) == 4
    denied = client.post(
        f"/v1/actions/{archive['id']}/decision", json={"version": 0, "decision": "approve"}
    )
    assert denied.status_code == 403
    gov.actor = "member"
    assert (
        client.post(
            f"/v1/actions/{archive['id']}/decision", json={"version": 0, "decision": "approve"}
        ).status_code
        == 403
    )
    gov.actor = "external"
    assert gov.actions() == []
    assert client.get(f"/v1/actions/{archive['id']}").status_code == 404
    assert (
        client.post(
            f"/v1/actions/{archive['id']}/decision", json={"version": 0, "decision": "approve"}
        ).status_code
        == 404
    )

    gov.actor = "reviewer"
    no_reason = client.post(
        f"/v1/actions/{archive['id']}/decision", json={"version": 0, "decision": "reject"}
    )
    assert no_reason.status_code == 422
    stale = client.post(
        f"/v1/actions/{archive['id']}/decision", json={"version": 3, "decision": "approve"}
    )
    assert stale.status_code == 409
    approved = client.post(
        f"/v1/actions/{archive['id']}/decision",
        json={"version": 0, "decision": "approve", "comment": "Looks right"},
    )
    assert approved.status_code == 200, approved.text
    body = approved.json()
    assert body["status"] == "approved" and body["version"] == 1
    assert (
        body["decided_by_email"] == "reviewer@example.com"
        and body["decision_comment"] == "Looks right"
    )
    again = client.post(
        f"/v1/actions/{archive['id']}/decision", json={"version": 1, "decision": "approve"}
    )
    assert again.status_code == 409
    hook = rows["hook"]
    assert (
        client.post(
            f"/v1/actions/{hook['id']}/decision", json={"version": 0, "decision": "approve"}
        ).status_code
        == 409
    )
    with Session(gov.engine) as session:
        events = session.scalars(
            select(OutboxEvent).where(
                OutboxEvent.document_id == gov.document_id, OutboxEvent.topic == "execute_action"
            )
        ).all()
        assert sorted(str(event.action_id) for event in events) == sorted(
            [hook["id"], archive["id"]]
        )
    assert gov.audits("action.approved")[-1]["comment"] == "Looks right"

    ghost = rows["ghost"]
    assert client.post(f"/v1/actions/{ghost['id']}/retry", json={"version": 0}).status_code == 200
    retried = client.get(f"/v1/actions/{ghost['id']}").json()
    assert retried["status"] == "approved" and retried["attempts"] == 0 and retried["error"] is None
    assert retried["version"] == 1
    assert gov.audits("action.retried") == [
        gov.audits("action.retried")[0] | {"from_status": "failed", "destination": "ghost"}
    ]
    assert client.post(f"/v1/actions/{archive['id']}/retry", json={"version": 1}).status_code == 409
    assert client.post(f"/v1/actions/{ghost['id']}/retry", json={"version": 0}).status_code == 409
    ledger = rows["ledger"]
    assert client.post(f"/v1/actions/{ledger['id']}/retry", json={"version": 0}).status_code == 409

    # Rejecting the last open proposal settles the document once nothing is pending.
    with Session(gov.engine) as session, session.begin():
        for row in session.scalars(select(Action).where(Action.document_id == gov.document_id)):
            if row.status == "approved":
                row.status = "succeeded"
        fresh = make_document(gov.org_id, gov.actors["member"], "third.pdf", "approved")
        session.add(fresh)
        session.flush()
        add_fields(session, fresh, {"vendor": "Third", "invoice_number": "T-3", "total": "$7.00"})
        third_id = fresh.id
    created = {action.destination: action for action in gov.propose(third_id)}
    rejected = client.post(
        f"/v1/actions/{created['archive'].id}/decision",
        json={"version": 0, "decision": "reject", "comment": "Not this month"},
    )
    assert rejected.status_code == 200 and rejected.json()["status"] == "rejected"
    listed = {row["id"]: row["status"] for row in client.get("/v1/documents").json()}
    assert listed[str(third_id)] == "actions_pending"  # the auto hook action is still approved
    with Session(gov.engine) as session, session.begin():
        for row in session.scalars(select(Action).where(Action.document_id == third_id)):
            if row.status in {"approved", "failed"}:
                row.status = "succeeded" if row.status == "approved" else "failed"
        document = session.get(Document, third_id)
        assert document is not None
        actions_service.recompute_document_status(session, document, NOW)
        assert document.status == "completed"
    assert [
        row["id"] for row in client.get("/v1/documents", params={"status": "completed"}).json()
    ] == [str(third_id)]
    assert str(gov.document_id) in {
        row["id"]
        for row in client.get("/v1/documents", params={"status": "actions_pending"}).json()
    }


def test_reopen_withdraws_proposals_and_timeline_shows_action_events(gov: Gov) -> None:
    created = {action.destination: action for action in gov.propose()}
    client = gov.client
    timeline = client.get(f"/v1/documents/{gov.document_id}/timeline").json()
    proposed = [entry for entry in timeline if entry["kind"] == "action"]
    assert [entry["event_type"] for entry in proposed] == ["action.proposed"] * 4
    assert proposed[0]["summary"] == "Proposed post webhook to hook"
    assert proposed[0]["detail"]["preview"]["kind"] == "post_webhook"
    assert proposed[0]["detail"]["policy_mode"] == "auto"
    assert "action.forbidden" in {entry["event_type"] for entry in timeline}
    assert not any(
        entry["kind"] == "audit" and entry["event_type"] == "action.proposed" for entry in timeline
    )
    with Session(gov.engine) as session, session.begin():
        ghost = session.get(Action, created["ghost"].id)
        assert ghost is not None
        ghost.status = "dead_lettered"
    workspace = client.get(f"/v1/documents/{gov.document_id}/workspace").json()
    assert workspace["capabilities"]["can_review"] is True
    reopened = client.post(
        f"/v1/documents/{gov.document_id}/review",
        json={"version": workspace["version"], "decision": "reopen"},
    )
    assert reopened.status_code == 200, reopened.text
    rows = gov.by_destination()
    assert rows["archive"]["status"] == "rejected"
    assert rows["archive"]["decision_comment"] == "Superseded: document reopened"
    assert rows["archive"]["decided_by_email"] == "admin@example.com"
    # Auto-approved but never started, and dead-lettered, actions are superseded as well;
    # a forbidden one is already settled.
    assert rows["hook"]["status"] == "rejected"
    assert rows["ghost"]["status"] == "rejected"
    assert rows["ledger"]["status"] == "forbidden"
    assert client.get(f"/v1/documents/{gov.document_id}").json()["status"] == "needs_review"
    withdrawn = [event for event in gov.audits("action.rejected") if event.get("withdrawn")]
    assert {event["action_id"] for event in withdrawn} == {
        str(created[name].id) for name in ("hook", "archive", "ghost")
    }
    assert {event["from_status"] for event in withdrawn} == {
        "approved",
        "proposed",
        "dead_lettered",
    }
    assert all(event["reason"] == "Superseded: document reopened" for event in withdrawn)


# Exports


def test_exports_listing_and_download(gov: Gov) -> None:
    client = gov.client
    archive_id = gov.connectors["archive"]
    key = export_key(gov.org_id, archive_id, "2026-09")
    gov.store.put(key, b"opspilot_idempotency_key,vendor\nk1,Harbor Supply Ltd\n")
    with Session(gov.engine) as session, session.begin():
        session.add(
            Action(
                id=uuid.uuid4(),
                org_id=gov.org_id,
                document_id=gov.document_id,
                connector_id=archive_id,
                action_type="export_csv",
                destination="archive",
                payload_json="{}",
                preview_json="{}",
                status="succeeded",
                policy_mode="auto",
                idempotency_key="k1",
                attempts=1,
                proposed_at=NOW,
                executed_at=NOW,
                result_json=json.dumps({"external_id": key}),
                version=2,
            )
        )
    months = client.get("/v1/exports", params={"connector_id": str(archive_id)})
    assert months.status_code == 200, months.text
    assert months.json() == [
        {
            "connector_id": str(archive_id),
            "month": "2026-09",
            "path": f"/v1/exports/{archive_id}/2026-09.csv",
        }
    ]
    download = client.get(f"/v1/exports/{archive_id}/2026-09.csv")
    assert download.status_code == 200, download.text
    assert download.headers["content-type"].startswith("text/csv")
    assert download.headers["content-disposition"] == "attachment; filename*=UTF-8''ap-2026-09.csv"
    assert "no-store" in download.headers["cache-control"]
    assert download.text.splitlines()[1] == "k1,Harbor Supply Ltd"
    assert client.get(f"/v1/exports/{archive_id}/2025-01.csv").status_code == 404
    assert client.get(f"/v1/exports/{archive_id}/2026-13.csv").status_code == 422
    assert client.get(f"/v1/exports/{gov.connectors['hook']}/2026-09.csv").status_code == 404
    assert (
        client.get("/v1/exports", params={"connector_id": str(gov.connectors["hook"])}).status_code
        == 404
    )
    # Export files are organization-wide sinks that may hold restricted rows: admins only.
    for actor in ("reviewer", "member", "viewer"):
        gov.actor = actor
        assert client.get(f"/v1/exports/{archive_id}/2026-09.csv").status_code == 403
        assert (
            client.get("/v1/exports", params={"connector_id": str(archive_id)}).status_code == 403
        )
    gov.actor = "external"
    assert client.get(f"/v1/exports/{archive_id}/2026-09.csv").status_code == 404


def test_connector_test_is_refused_while_the_agent_is_paused(
    gov: Gov, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeConnector()
    monkeypatch.setattr(settings_service, "get_connector", lambda kind: fake)
    client = gov.client
    assert (
        client.post("/v1/settings/policies", json={"version": 0, "kill_switch": True}).status_code
        == 200
    )
    paused = client.post(f"/v1/settings/connectors/{gov.connectors['hook']}/test")
    assert paused.status_code == 409
    assert paused.json()["error"]["message"].startswith("Agent paused")
    assert fake.calls == []
    listed = {row["name"]: row for row in client.get("/v1/settings/connectors").json()}
    assert listed["hook"]["last_test_at"] is None
    assert (
        client.post("/v1/settings/policies", json={"version": 1, "kill_switch": False}).status_code
        == 200
    )
    resumed = client.post(f"/v1/settings/connectors/{gov.connectors['hook']}/test")
    assert resumed.status_code == 200 and resumed.json()["ok"] is True
    assert len(fake.calls) == 1
    listed = {row["name"]: row for row in client.get("/v1/settings/connectors").json()}
    assert listed["hook"]["last_test_ok"] is True and listed["hook"]["version"] == 1


def test_connector_config_change_supersedes_unapproved_actions(gov: Gov) -> None:
    created = {action.destination: action for action in gov.propose()}
    client = gov.client
    archive_id, hook_id = gov.connectors["archive"], gov.connectors["hook"]
    # Renaming or deactivating does not touch actions; only a configuration change does.
    renamed = client.post(
        f"/v1/settings/connectors/{archive_id}", json={"version": 1, "name": "archive-2"}
    )
    assert renamed.status_code == 200, renamed.text
    assert gov.by_destination()["archive"]["status"] == "proposed"
    restored = client.post(
        f"/v1/settings/connectors/{archive_id}", json={"version": 2, "name": "archive"}
    )
    assert restored.status_code == 200, restored.text
    changed = client.post(
        f"/v1/settings/connectors/{archive_id}",
        json={"version": 3, "config": {"file_prefix": "renamed"}},
    )
    assert changed.status_code == 200, changed.text
    rows = gov.by_destination()
    assert rows["archive"]["status"] == "rejected"
    assert rows["archive"]["decision_comment"] == "Superseded: connector changed"
    assert rows["archive"]["decided_by_email"] == "admin@example.com"
    assert rows["hook"]["status"] == "approved"
    assert gov.audits("connector.updated")[-1]["changes"]["superseded_actions"] == 1
    # A human-approved action keeps its approval; an automatic, unstarted one does not.
    with Session(gov.engine) as session, session.begin():
        fresh = make_document(gov.org_id, gov.actors["member"], "fourth.pdf", "approved")
        session.add(fresh)
        session.flush()
        add_fields(session, fresh, {"vendor": "Fourth", "invoice_number": "F-4", "total": "$4.00"})
        fourth_id = fresh.id
    fourth = {action.destination: action for action in gov.propose(fourth_id)}
    gov.actor = "reviewer"
    approved = client.post(
        f"/v1/actions/{fourth['archive'].id}/decision", json={"version": 0, "decision": "approve"}
    )
    assert approved.status_code == 200, approved.text
    gov.actor = "admin"
    changed_hook = client.post(
        f"/v1/settings/connectors/{hook_id}",
        json={"version": 1, "config": {"url": "http://localhost:9/hook-v2"}},
    )
    assert changed_hook.status_code == 200, changed_hook.text
    statuses = {
        (row["document_id"], row["destination"]): row["status"] for row in gov.actions(limit=100)
    }
    assert statuses[(str(gov.document_id), "hook")] == "rejected"
    assert statuses[(str(fourth_id), "hook")] == "rejected"
    assert gov.audits("connector.updated")[-1]["changes"]["superseded_actions"] == 2
    changed_archive = client.post(
        f"/v1/settings/connectors/{archive_id}",
        json={"version": 4, "config": {"file_prefix": "again"}},
    )
    assert changed_archive.status_code == 200, changed_archive.text
    assert client.get(f"/v1/actions/{fourth['archive'].id}").json()["status"] == "approved"
    assert client.get(f"/v1/documents/{gov.document_id}").json()["status"] == "completed"
    assert {row["status"] for row in gov.actions(document_id=str(gov.document_id))} == {
        "rejected",
        "forbidden",
        "failed",
    }
    assert created["archive"].id != fourth["archive"].id


def test_retry_and_decision_roles_and_restricted_documents(gov: Gov) -> None:
    created = {action.destination: action for action in gov.propose()}
    client = gov.client
    ghost, archive = created["ghost"], created["archive"]
    for actor in ("member", "viewer"):
        gov.actor = actor
        assert client.post(f"/v1/actions/{ghost.id}/retry", json={"version": 0}).status_code == 403
    gov.actor = "reviewer"
    assert client.get(f"/v1/actions/{archive.id}").status_code == 200
    with Session(gov.engine) as session, session.begin():
        metadata = session.get(InvoiceMetadata, gov.document_id)
        assert metadata is not None
        metadata.visibility = "restricted"
    # A reviewer without an assignment or grant cannot see, decide or retry actions of a
    # restricted document; the uploader can see them but cannot decide.
    assert gov.actions() == []
    assert client.get(f"/v1/actions/{archive.id}").status_code == 404
    assert (
        client.post(
            f"/v1/actions/{archive.id}/decision", json={"version": 0, "decision": "approve"}
        ).status_code
        == 404
    )
    assert client.post(f"/v1/actions/{ghost.id}/retry", json={"version": 0}).status_code == 404
    gov.actor = "member"
    assert len(gov.actions()) == 4
    assert (
        client.post(
            f"/v1/actions/{archive.id}/decision", json={"version": 0, "decision": "approve"}
        ).status_code
        == 403
    )
    gov.actor = "admin"
    assert len(gov.actions()) == 4
    assert (
        client.post(
            f"/v1/actions/{archive.id}/decision", json={"version": 0, "decision": "approve"}
        ).status_code
        == 200
    )


def test_spend_cap_is_set_cleared_and_audited(gov: Gov) -> None:
    client = gov.client
    assert client.get("/v1/settings/policies").json()["daily_llm_spend_cap_cents"] is None
    capped = client.post(
        "/v1/settings/policies", json={"version": 0, "daily_llm_spend_cap_cents": 250}
    )
    assert capped.status_code == 200, capped.text
    assert capped.json()["daily_llm_spend_cap_cents"] == 250 and capped.json()["version"] == 1
    # Omitting the field leaves the cap alone; sending null removes it.
    kept = client.post("/v1/settings/policies", json={"version": 1, "shadow_mode": True})
    assert kept.json()["daily_llm_spend_cap_cents"] == 250
    cleared = client.post(
        "/v1/settings/policies", json={"version": 2, "daily_llm_spend_cap_cents": None}
    )
    assert cleared.status_code == 200 and cleared.json()["daily_llm_spend_cap_cents"] is None
    assert (
        client.post(
            "/v1/settings/policies", json={"version": 3, "daily_llm_spend_cap_cents": -1}
        ).status_code
        == 422
    )
    assert gov.audits("settings.spend_cap_changed") == [
        {"from": None, "to": 250},
        {"from": 250, "to": None},
    ]
    with Session(gov.engine) as session:
        settings = session.get(OrgSettings, gov.org_id)
        assert settings is not None and settings.daily_llm_spend_cap_cents is None
    gov.actor = "external"
    assert client.get("/v1/settings/policies").json()["daily_llm_spend_cap_cents"] is None
