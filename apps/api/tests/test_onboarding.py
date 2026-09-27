"""Organization signup, approval, account ownership and immediate revocation."""

import json
import os
import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.auth import cookie_identity
from app.db import SessionLocal, normalize_database_url, set_org_context
from app.login_throttle import identity_hash
from app.main import app
from app.models import AuditEvent, LoginAttempt, Membership, Organization, User, WorkflowConfig
from app.security import make_session_token

PASSWORD = "Test-workspace-pass123"
postgres = pytest.mark.skipif(
    "DATABASE_OWNER_URL" not in os.environ, reason="Postgres integration test"
)


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as value:
        try:
            yield value
        finally:
            org_ids = value.app_state.get("onboarding_test_orgs", [])
            if org_ids:
                engine = create_engine(normalize_database_url(os.environ["DATABASE_OWNER_URL"]))
                with Session(engine) as session, session.begin():
                    user_ids = session.scalars(
                        select(Membership.user_id).where(Membership.org_id.in_(org_ids))
                    ).all()
                    for table in (AuditEvent, Membership, WorkflowConfig):
                        session.execute(delete(table).where(table.org_id.in_(org_ids)))
                    session.execute(delete(Organization).where(Organization.id.in_(org_ids)))
                    session.execute(
                        delete(User).where(
                            User.id.in_(user_ids), ~User.id.in_(select(Membership.user_id))
                        )
                    )
                    # Keep repeated runs from exhausting the test client's peer limit.
                    session.execute(
                        delete(LoginAttempt).where(
                            LoginAttempt.identity_hash == identity_hash("signup-peer", "testclient")
                        )
                    )
                engine.dispose()


def signup(client: TestClient, **overrides: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    suffix = uuid.uuid4().hex
    payload = {
        "org_name": f"New workspace {suffix}",
        "org_slug": f"workspace-{suffix}",
        "email": f"owner-{suffix}@example.com",
        "password": PASSWORD,
        "default_currency": "INR",
        **overrides,
    }
    response = client.post("/v1/auth/register-organization", json=payload)
    assert response.status_code == 201, response.text
    client.app_state.setdefault("onboarding_test_orgs", []).append(
        uuid.UUID(response.json()["org_id"])
    )
    return payload, response.json()


def request_membership(client: TestClient, slug: str) -> dict[str, Any]:
    payload = {
        "org_slug": slug,
        "email": f"applicant-{uuid.uuid4().hex}@example.com",
        "password": PASSWORD,
        "requested_role": "reviewer",
    }
    response = client.post("/v1/auth/join-organization", json=payload)
    assert response.status_code == 201, response.text
    assert response.json()["status"] == "pending"
    assert "opspilot_session" not in client.cookies
    return payload


def login(client: TestClient, payload: dict[str, Any]) -> Any:
    return client.post(
        "/v1/auth/login", json={key: payload[key] for key in ("org_slug", "email", "password")}
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"password": "too-short1"},
        {"password": "no-numbers-in-password"},
        {"password": "1" * 129},
        {"org_name": "  "},
        {"org_slug": "-invalid"},
        {"org_slug": "space not allowed"},
        {"org_slug": "a" * 81},
        {"default_currency": "$$$$"},
    ],
)
def test_signup_validates_before_database_work(client: TestClient, changes: dict[str, Any]) -> None:
    response = client.post(
        "/v1/auth/register-organization",
        json={
            "org_name": "Acme",
            "org_slug": "acme",
            "email": "admin@example.com",
            "password": PASSWORD,
            **changes,
        },
    )
    assert response.status_code == 422


def test_public_join_cannot_request_admin(client: TestClient) -> None:
    response = client.post(
        "/v1/auth/join-organization",
        json={
            "org_slug": "acme",
            "email": "member@example.com",
            "password": PASSWORD,
            "requested_role": "admin",
        },
    )
    assert response.status_code == 422


@postgres
def test_create_workspace_provisions_active_admin_and_workflow(client: TestClient) -> None:
    payload, identity = signup(client)
    assert identity["role"] == "admin"
    assert identity["org_slug"] == payload["org_slug"]
    assert identity["default_currency"] == "INR"
    assert client.get("/v1/auth/me").json() == identity
    with SessionLocal() as session:
        set_org_context(session, uuid.UUID(identity["org_id"]))
        assert (
            session.scalar(
                select(WorkflowConfig).where(WorkflowConfig.org_id == identity["org_id"])
            )
            is not None
        )
        assert (
            session.scalar(
                select(AuditEvent).where(AuditEvent.event_type == "organization.created")
            )
            is not None
        )
    member = client.get("/v1/organization/members").json()[0]
    assert member["status"] == "active"
    assert member["requested_role"] == "admin"
    assert member["decided_at"] is not None
    duplicate = client.post("/v1/auth/register-organization", json=payload)
    assert duplicate.status_code == 409


@postgres
def test_directory_returns_names_only_and_literal_search(client: TestClient) -> None:
    payload, _ = signup(client)
    listing = client.get("/v1/organizations", params={"search": payload["org_slug"]})
    assert listing.status_code == 200
    assert len(listing.json()) == 1
    assert set(listing.json()[0]) == {"id", "slug", "name"}
    assert client.get("/v1/organizations", params={"search": "%"}).json() == []
    assert len(client.get("/v1/organizations").json()) <= 50


@postgres
def test_pending_then_approved_then_suspended_session(client: TestClient) -> None:
    owner, identity = signup(client)
    applicant = request_membership(client, owner["org_slug"])
    denied = login(client, applicant)
    assert denied.status_code == 403
    assert "awaiting approval" in denied.json()["error"]["message"]
    assert client.get("/v1/documents").status_code == 401
    assert login(client, owner).status_code == 200
    pending = next(
        row
        for row in client.get("/v1/organization/members").json()
        if row["email"] == applicant["email"]
    )
    assert pending["status"] == "pending"
    assert pending["requested_role"] == "reviewer"
    route = f"/v1/organization/members/{pending['user_id']}/decision"
    approved = client.post(route, json={"decision": "approved", "role": "reviewer"})
    assert approved.status_code == 200
    assert approved.json()["status"] == "active"
    with TestClient(app) as member_client:
        assert login(member_client, applicant).status_code == 200
        assert member_client.get("/v1/documents").status_code == 200
        assert member_client.get("/v1/organization/members").status_code == 403
        assert (
            member_client.post(route, json={"decision": "approved", "role": "reviewer"}).status_code
            == 403
        )
        assert client.post(route, json={"decision": "suspended"}).status_code == 200
        # A previously valid signed cookie stops working immediately, without expiry.
        assert member_client.get("/v1/auth/me").status_code == 403
        assert member_client.get("/v1/documents").status_code == 403
        assert login(member_client, applicant).status_code == 403
        restored = client.post(route, json={"decision": "approved", "role": "viewer"})
        assert restored.status_code == 200
        assert login(member_client, applicant).json()["role"] == "viewer"
        with SessionLocal() as session:
            set_org_context(session, uuid.UUID(identity["org_id"]))
            events = session.scalars(select(AuditEvent.event_type)).all()
            assert "membership.suspended" in events and events.count("membership.approved") == 2


@postgres
def test_admin_cannot_escalate_role_or_modify_admin(client: TestClient) -> None:
    owner, identity = signup(client)
    request_membership(client, owner["org_slug"])
    assert login(client, owner).status_code == 200
    pending = next(
        row for row in client.get("/v1/organization/members").json() if row["status"] == "pending"
    )
    assert (
        client.post(
            f"/v1/organization/members/{pending['user_id']}/decision",
            json={
                "decision": "approved",
                "role": "admin",
            },
        ).status_code
        == 422
    )
    for decision in ("rejected", "suspended", "approved"):
        response = client.post(
            f"/v1/organization/members/{identity['user_id']}/decision",
            json={
                "decision": decision,
                "role": "viewer",
            },
        )
        assert response.status_code == 409
    assert client.get("/v1/auth/me").json()["role"] == "admin"


@postgres
def test_existing_email_requires_password_for_signup_and_join(client: TestClient) -> None:
    owner, identity = signup(client)
    _, other_identity = signup(client)
    slug = other_identity["org_slug"]
    for path, payload in (
        ("/v1/auth/register-organization", {**owner, "org_slug": f"new-{uuid.uuid4().hex}"}),
        ("/v1/auth/join-organization", {**owner, "org_slug": slug, "requested_role": "member"}),
    ):
        response = client.post(path, json={**payload, "password": "Wrong-account-pass123"})
        assert response.status_code == 401
    assert login(client, owner).status_code == 200
    assert client.get("/v1/auth/me").json()["user_id"] == identity["user_id"]
    joined = client.post(
        "/v1/auth/join-organization", json={**owner, "org_slug": slug, "requested_role": "member"}
    )
    assert joined.status_code == 201
    # Existing account's admin access to its first org still uses the original password.
    assert login(client, owner).json()["role"] == "admin"


@postgres
def test_admin_decisions_and_members_are_tenant_isolated(client: TestClient) -> None:
    owner, identity = signup(client)
    applicant = request_membership(client, owner["org_slug"])
    assert login(client, owner).status_code == 200
    pending = next(
        row
        for row in client.get("/v1/organization/members").json()
        if row["email"] == applicant["email"]
    )
    _, other_identity = signup(client)
    listing = client.get("/v1/organization/members").json()
    assert [row["user_id"] for row in listing] == [other_identity["user_id"]]
    assert (
        client.post(
            f"/v1/organization/members/{pending['user_id']}/decision",
            json={
                "decision": "approved",
                "role": "member",
            },
        ).status_code
        == 404
    )
    with SessionLocal() as session:
        set_org_context(session, uuid.UUID(identity["org_id"]))
        member = session.scalar(select(Membership).where(Membership.user_id == pending["user_id"]))
        assert member is not None and member.status == "pending"


@postgres
def test_rejection_is_actionable_and_duplicate_join_does_not_reset_it(client: TestClient) -> None:
    owner, _ = signup(client)
    applicant = request_membership(client, owner["org_slug"])
    assert login(client, owner).status_code == 200
    pending = next(
        row
        for row in client.get("/v1/organization/members").json()
        if row["email"] == applicant["email"]
    )
    assert (
        client.post(
            f"/v1/organization/members/{pending['user_id']}/decision",
            json={
                "decision": "rejected",
            },
        ).json()["status"]
        == "rejected"
    )
    response = login(client, applicant)
    assert response.status_code == 403
    assert "declined" in response.json()["error"]["message"]
    assert client.post("/v1/auth/join-organization", json=applicant).status_code == 409


@postgres
def test_membership_write_grants_still_enforce_tenant_rls(client: TestClient) -> None:
    _, first = signup(client)
    _, second = signup(client)
    with SessionLocal() as session:
        assert session.scalar(text("SELECT current_user")) == "opspilot_app"
        set_org_context(session, uuid.UUID(first["org_id"]))
        assert (
            session.scalar(select(Membership).where(Membership.org_id == second["org_id"])) is None
        )
        with pytest.raises(DBAPIError):
            session.execute(
                text(
                    "INSERT INTO memberships (id, org_id, user_id, role, status) "
                    "VALUES (gen_random_uuid(), :org, :user, 'member', 'active')"
                ),
                {"org": second["org_id"], "user": first["user_id"]},
            )
        session.rollback()
        set_org_context(session, uuid.UUID(first["org_id"]))
        # Even with UPDATE permission, other tenants' members are invisible.
        affected = session.execute(
            text("UPDATE memberships SET status='suspended' WHERE org_id=:org RETURNING id"),
            {"org": second["org_id"]},
        )
        assert affected.scalars().all() == []


@postgres
def test_suspension_waits_for_inflight_authorized_transaction(client: TestClient) -> None:
    owner, identity = signup(client)
    applicant = request_membership(client, owner["org_slug"])
    assert login(client, owner).status_code == 200
    pending = next(
        row
        for row in client.get("/v1/organization/members").json()
        if row["email"] == applicant["email"]
    )
    route = f"/v1/organization/members/{pending['user_id']}/decision"
    assert client.post(route, json={"decision": "approved", "role": "member"}).status_code == 200
    token = make_session_token(uuid.UUID(pending["user_id"]), uuid.UUID(identity["org_id"]))
    with ThreadPoolExecutor(max_workers=1) as executor, SessionLocal() as session:
        assert cookie_identity(session, token)[3].status == "active"
        future = executor.submit(client.post, route, json={"decision": "suspended"})
        try:
            with pytest.raises(TimeoutError):
                future.result(timeout=0.2)
        finally:
            session.rollback()
        assert future.result(timeout=5).status_code == 200
    with TestClient(app) as applicant_client:
        applicant_client.cookies.set("opspilot_session", token)
        assert applicant_client.get("/v1/auth/me").status_code == 403


@postgres
def test_registration_template_chooses_the_starting_workflow(client: TestClient) -> None:
    _, identity = signup(client, template="logistics")
    workflow = client.get("/v1/settings/workflow")
    assert workflow.status_code == 200, workflow.text
    assert [item["name"] for item in workflow.json()["config"]["document_types"]] == [
        "purchase_order",
        "delivery_note",
        "invoice",
    ]
    with SessionLocal() as session:
        set_org_context(session, uuid.UUID(identity["org_id"]))
        created = session.scalar(
            select(AuditEvent).where(
                AuditEvent.org_id == uuid.UUID(identity["org_id"]),
                AuditEvent.event_type == "organization.created",
            )
        )
        assert created is not None
        assert json.loads(created.detail_json)["template"] == "logistics"
    _, plain = signup(client)
    default = client.get("/v1/settings/workflow").json()
    assert [item["name"] for item in default["config"]["document_types"]] == ["invoice"]
    assert plain["org_id"] != identity["org_id"]
    invalid = client.post(
        "/v1/auth/register-organization",
        json={
            "org_name": "Acme",
            "org_slug": f"acme-{uuid.uuid4().hex[:8]}",
            "email": f"owner-{uuid.uuid4().hex}@example.com",
            "password": PASSWORD,
            "template": "receipts",
        },
    )
    assert invalid.status_code == 422
