"""API keys: format, administrator lifecycle, and Bearer intake over real authentication."""

import json
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import pytest
from fastapi.testclient import TestClient
from scripts.generate_demo_invoice import invoice_pdf
from sqlalchemy import Engine, create_engine, delete, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import api_keys
from app.api_keys import generate_key, hash_key, parse_key
from app.auth import current_session
from app.db import SessionLocal, set_org_context
from app.intake_models import ApiKey
from app.login_throttle import identity_hash
from app.main import app
from app.models import (
    AuditEvent,
    Base,
    LoginAttempt,
    Membership,
    Organization,
    User,
    WorkflowConfig,
)
from app.storage import get_store
from app.workflow_config import default_invoice_config
from tests.conftest import Tenant, TenantFactory, owner_engine, postgres
from tests.test_documents import MemoryStore, tenant_login


def test_key_format_hashing_and_parsing() -> None:
    generated = generate_key()
    assert generated.plaintext.startswith(f"opk_{generated.prefix}_")
    assert len(generated.prefix) == 8 and len(generated.plaintext) > 40
    assert parse_key(generated.plaintext) == generated.prefix
    assert parse_key(f"  {generated.plaintext}\n") == generated.prefix
    assert hash_key(generated.plaintext) == generated.key_hash and len(generated.key_hash) == 64
    assert generated.key_hash != generated.plaintext
    for bad in ("", "opk_short", "Bearer x", "opk_ZZZZZZZZ_" + "a" * 40, "opk_deadbeef_short"):
        assert parse_key(bad) is None
    assert generate_key().plaintext != generated.plaintext


@dataclass
class Keys:
    client: TestClient
    engine: Engine
    actors: dict[str, uuid.UUID]
    org_id: uuid.UUID
    other_org_id: uuid.UUID
    actor: str = "admin"

    def create(self, name: str = "ci-bot") -> Any:
        return self.client.post("/v1/settings/api-keys", json={"name": name})

    def audits(self, event_type: str) -> list[dict[str, Any]]:
        with Session(self.engine) as session:
            rows = session.scalars(
                select(AuditEvent).where(
                    AuditEvent.org_id == self.org_id, AuditEvent.event_type == event_type
                )
            )
            return [json.loads(row.detail_json) for row in rows]


@pytest.fixture
def keys() -> Iterator[Keys]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    org_id, other_org = uuid.uuid4(), uuid.uuid4()
    actors = {name: uuid.uuid4() for name in ("admin", "viewer", "external")}
    with Session(engine) as session:
        session.add_all(
            [
                Organization(id=org_id, slug="keyed", name="Keyed"),
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
                    org_id=target, version=1, config_json=default_invoice_config().model_dump_json()
                )
            )
        session.commit()
    with TestClient(app) as client:
        state = Keys(client, engine, actors, org_id, other_org)

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


def test_admin_creates_lists_and_revokes_keys_without_exposing_secrets(keys: Keys) -> None:
    client = keys.client
    created = keys.create()
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["key"].startswith("opk_") and body["key_prefix"] == body["key"].split("_")[1]
    assert body["name"] == "ci-bot" and body["scopes"] == "documents:write"
    assert body["created_by_email"] == "admin@example.com"
    assert body["revoked_at"] is None and body["last_used_at"] is None
    listed = client.get("/v1/settings/api-keys")
    assert listed.status_code == 200
    assert len(listed.json()) == 1
    row = listed.json()[0]
    assert "key" not in row and row["key_prefix"] == body["key_prefix"] and row["id"] == body["id"]
    with Session(keys.engine) as session:
        stored = session.get(ApiKey, uuid.UUID(body["id"]))
        assert stored is not None
        assert stored.key_hash == hash_key(body["key"]) and body["key"] not in stored.key_hash
    assert keys.audits("api_key.created") == [
        {"api_key_id": body["id"], "key_prefix": body["key_prefix"], "name": "ci-bot"}
    ]

    revoked = client.post(f"/v1/settings/api-keys/{body['id']}/revoke")
    assert revoked.status_code == 200, revoked.text
    assert revoked.json()["revoked_at"] is not None
    again = client.post(f"/v1/settings/api-keys/{body['id']}/revoke")
    assert again.status_code == 200
    # SQLite hands back the stored timestamp without its zone marker.
    assert again.json()["revoked_at"].rstrip("Z") == revoked.json()["revoked_at"].rstrip("Z")
    assert len(keys.audits("api_key.revoked")) == 1
    assert client.post(f"/v1/settings/api-keys/{uuid.uuid4()}/revoke").status_code == 404
    for payload in ({"name": ""}, {"name": "x" * 101}, {"name": "ok", "scopes": "*"}, {}):
        assert client.post("/v1/settings/api-keys", json=payload).status_code == 422

    keys.actor = "viewer"
    assert client.get("/v1/settings/api-keys").status_code == 403
    assert keys.create().status_code == 403
    assert client.post(f"/v1/settings/api-keys/{body['id']}/revoke").status_code == 403

    keys.actor = "external"
    assert client.get("/v1/settings/api-keys").json() == []
    assert client.post(f"/v1/settings/api-keys/{body['id']}/revoke").status_code == 404


def test_active_key_limit_counts_only_live_keys(
    keys: Keys, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(api_keys, "MAX_KEYS_PER_ORG", 1)
    first = keys.create("one")
    assert first.status_code == 201
    assert keys.create("two").status_code == 409
    assert keys.client.post(f"/v1/settings/api-keys/{first.json()['id']}/revoke").status_code == 200
    assert keys.create("two").status_code == 201


def test_bearer_header_is_refused_on_routes_outside_intake() -> None:
    with TestClient(app) as client:
        response = client.get("/v1/actions", headers={"Authorization": "Bearer opk_x"})
    assert response.status_code == 401
    assert response.json()["error"]["message"] == "API keys can only submit and poll documents"


def _clear_key_budget(key_ids: list[str]) -> None:
    engine = owner_engine()
    try:
        with Session(engine) as session, session.begin():
            session.execute(
                delete(LoginAttempt).where(
                    LoginAttempt.identity_hash.in_(
                        [identity_hash(api_keys.THROTTLE_SCOPE, key_id) for key_id in key_ids]
                    )
                )
            )
    finally:
        engine.dispose()


def _issue_key(tenant: Tenant, name: str = "ci-bot") -> dict[str, Any]:
    with TestClient(app) as admin:
        tenant_login(admin, tenant, "admin")
        created = admin.post("/v1/settings/api-keys", json={"name": name})
        assert created.status_code == 201, created.text
        return dict(created.json())


@postgres
def test_api_key_authenticates_only_document_intake_and_polling(
    make_tenant: TenantFactory,
) -> None:
    tenant, other = make_tenant(), make_tenant()
    store = MemoryStore()
    app.dependency_overrides[get_store] = lambda: store
    issued = _issue_key(tenant)
    foreign = _issue_key(other, "other-bot")
    key, other_key = issued["key"], foreign["key"]
    try:
        with TestClient(app) as api:
            headers = {"Authorization": f"Bearer {key}"}
            uploaded = api.post(
                "/v1/documents",
                files={
                    "file": ("bot.pdf", invoice_pdf(invoice_number="KEY-0001"), "application/pdf")
                },
                headers=headers,
            )
            assert uploaded.status_code == 202, uploaded.text
            body = uploaded.json()
            assert body["source"] == "api" and body["source_ref"] == "API key ci-bot"
            document_id = body["id"]
            detail = api.get(f"/v1/documents/{document_id}", headers=headers)
            assert detail.status_code == 200 and detail.json()["source"] == "api"
            assert detail.json()["context_text"] is None
            for method, path in (
                ("GET", "/v1/documents"),
                ("GET", "/v1/review/queue"),
                ("GET", "/v1/auth/me"),
                ("GET", "/v1/settings/api-keys"),
                ("POST", f"/v1/documents/{document_id}/retry"),
                ("GET", f"/v1/documents/{document_id}/file"),
            ):
                refused = api.request(method, path, headers=headers)
                assert refused.status_code == 401, (method, path, refused.text)
                assert refused.json()["error"]["message"] == (
                    "API keys can only submit and poll documents"
                )
            assert (
                api.get(
                    f"/v1/documents/{document_id}",
                    headers={"Authorization": f"Bearer {other_key}"},
                ).status_code
                == 404
            )
            forged = f"opk_{key.split('_')[1]}_" + "x" * 40
            for bad in ("Bearer nope", f"Bearer {forged}", "Basic abc", "Bearer "):
                refused = api.get(f"/v1/documents/{document_id}", headers={"Authorization": bad})
                assert refused.status_code == 401, bad
                assert refused.json()["error"]["message"] == "Invalid API key"
            assert api.get(f"/v1/documents/{document_id}").status_code == 401

        with SessionLocal() as session:
            set_org_context(session, tenant.org_id)
            received = session.scalar(
                select(AuditEvent).where(
                    AuditEvent.org_id == tenant.org_id,
                    AuditEvent.document_id == uuid.UUID(document_id),
                    AuditEvent.event_type == "document.received",
                )
            )
            assert received is not None
            assert received.actor_user_id == tenant.users["admin"]
            detail_json = json.loads(received.detail_json)
            assert detail_json["api_key_id"] == issued["id"] and detail_json["source"] == "api"
            stored = session.get(ApiKey, uuid.UUID(issued["id"]))
            assert stored is not None and stored.last_used_at is not None

        with TestClient(app) as admin:
            tenant_login(admin, tenant, "admin")
            listed = admin.get("/v1/settings/api-keys").json()
            assert [row["id"] for row in listed] == [issued["id"]]
            assert listed[0]["last_used_at"] is not None and "key" not in listed[0]
            assert admin.post(f"/v1/settings/api-keys/{issued['id']}/revoke").status_code == 200
            assert admin.post(f"/v1/settings/api-keys/{foreign['id']}/revoke").status_code == 404
        with TestClient(app) as api:
            refused = api.get(f"/v1/documents/{document_id}", headers=headers)
            assert refused.status_code == 401
            assert refused.json()["error"]["message"] == "API key has been revoked"
    finally:
        del app.dependency_overrides[get_store]
        _clear_key_budget([issued["id"], foreign["id"]])


@postgres
def test_api_key_upload_budget_and_owner_status(
    make_tenant: TenantFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(api_keys, "UPLOADS_PER_WINDOW", 2)
    tenant = make_tenant()
    store = MemoryStore()
    app.dependency_overrides[get_store] = lambda: store
    issued = _issue_key(tenant)
    headers = {"Authorization": f"Bearer {issued['key']}"}
    try:
        with TestClient(app) as api:
            ids = []
            for number in range(2):
                response = api.post(
                    "/v1/documents",
                    files={
                        "file": (
                            f"{number}.pdf",
                            invoice_pdf(invoice_number=f"BUDGET-{number}"),
                            "application/pdf",
                        )
                    },
                    headers=headers,
                )
                assert response.status_code == 202, response.text
                ids.append(response.json()["id"])
            throttled = api.post(
                "/v1/documents",
                files={
                    "file": ("2.pdf", invoice_pdf(invoice_number="BUDGET-2"), "application/pdf")
                },
                headers=headers,
            )
            assert throttled.status_code == 429
            assert "limit" in throttled.json()["error"]["message"]
            # Polling is not charged against the upload budget.
            assert api.get(f"/v1/documents/{ids[0]}", headers=headers).status_code == 200

        engine = owner_engine()
        with Session(engine) as session, session.begin():
            membership = session.scalar(
                select(Membership).where(
                    Membership.org_id == tenant.org_id,
                    Membership.user_id == tenant.users["admin"],
                )
            )
            assert membership is not None
            membership.status = "suspended"
        engine.dispose()
        with TestClient(app) as api:
            refused = api.get(f"/v1/documents/{ids[0]}", headers=headers)
            assert refused.status_code == 401
            assert refused.json()["error"]["message"] == (
                "API key owner is no longer an active member"
            )
    finally:
        del app.dependency_overrides[get_store]
        _clear_key_budget([issued["id"]])
