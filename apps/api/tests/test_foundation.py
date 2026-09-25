import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.db import get_session, set_org_context
from app.main import app
from app.models import Membership, Organization


def test_healthz() -> None:
    with TestClient(app) as client:
        response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["x-request-id"]


def test_error_envelopes_and_request_ids() -> None:
    with TestClient(app) as client:
        method = client.get("/v1/auth/login", headers={"X-Request-ID": "test-request-123"})
        assert method.status_code == 405
        assert method.json()["error"]["code"] == "request_failed"
        assert method.headers["x-request-id"] == "test-request-123"

        invalid = client.post(
            "/v1/auth/login", json={}, headers={"X-Request-ID": "invalid request id"}
        )
        assert invalid.status_code == 422
        assert invalid.json()["error"]["code"] == "validation_error"
        assert invalid.headers["x-request-id"] != "invalid request id"
        assert invalid.headers["x-request-id"]

    def broken_dependency() -> None:
        raise RuntimeError("private database detail")

    app.dependency_overrides[get_session] = broken_dependency
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            failed = client.get("/readyz", headers={"X-Request-ID": "failure-123"})
        assert failed.status_code == 500
        assert failed.json()["error"]["code"] == "internal_error"
        assert "private database detail" not in failed.text
        assert failed.headers["x-request-id"] == "failure-123"
    finally:
        del app.dependency_overrides[get_session]


@pytest.mark.skipif("DATABASE_OWNER_URL" not in os.environ, reason="Postgres integration test")
def test_login_and_tenant_isolation() -> None:
    owner_engine = create_engine(os.environ["DATABASE_OWNER_URL"])
    with Session(owner_engine) as owner:
        northwind = owner.scalar(select(Organization).where(Organization.slug == "northwind"))
        contoso = owner.scalar(select(Organization).where(Organization.slug == "contoso"))
        assert northwind is not None and contoso is not None

    with TestClient(app) as client:
        bad = client.post(
            "/v1/auth/login",
            json={
                "org_slug": "contoso",
                "email": "northwind@example.com",
                "password": os.environ["DEMO_PASSWORD"],
            },
        )
        assert bad.status_code == 401
        assert bad.json()["error"]["code"] == "unauthorized"
        unknown_user = client.post(
            "/v1/auth/login",
            json={
                "org_slug": "northwind",
                "email": "missing@example.com",
                "password": os.environ["DEMO_PASSWORD"],
            },
        )
        assert unknown_user.status_code == 401
        assert unknown_user.json() == bad.json()
        login = client.post(
            "/v1/auth/login",
            json={
                "org_slug": " Northwind ",
                "email": " NORTHWIND@example.com ",
                "password": os.environ["DEMO_PASSWORD"],
            },
        )
        assert login.status_code == 200
        assert login.json()["role"] == "admin"
        assert client.get("/v1/auth/me").json()["org_name"] == "Northwind Traders"
        members = client.get("/v1/organization/members")
        assert members.status_code == 200
        assert all("contoso" not in member["email"] for member in members.json())
        reviewer_login = client.post(
            "/v1/auth/login",
            json={
                "org_slug": "contoso",
                "email": "contoso@example.com",
                "password": os.environ["DEMO_PASSWORD"],
            },
        )
        assert reviewer_login.status_code == 200
        forbidden = client.get("/v1/organization/members")
        assert forbidden.status_code == 403
        assert forbidden.json()["error"]["code"] == "forbidden"

    app_engine = create_engine(os.environ["DATABASE_URL"])
    with Session(app_engine) as session:
        set_org_context(session, northwind.id)
        visible = session.scalars(select(Membership)).all()
        assert visible and all(item.org_id == northwind.id for item in visible)
        assert session.scalar(select(Membership).where(Membership.org_id == contoso.id)) is None
        session.execute(
            text(
                "INSERT INTO audit_events (id, org_id, event_type, detail_json) "
                "VALUES (gen_random_uuid(), :org, 'test', '{}')"
            ),
            {"org": northwind.id},
        )
        with pytest.raises(DBAPIError):
            session.execute(
                text("UPDATE audit_events SET event_type = 'changed' WHERE org_id = :org"),
                {"org": northwind.id},
            )
        session.rollback()
        set_org_context(session, northwind.id)
        # The DB policy also rejects a write outside the current org.
        with pytest.raises(DBAPIError):
            session.execute(
                text(
                    "INSERT INTO audit_events (id, org_id, event_type, detail_json) "
                    "VALUES (gen_random_uuid(), :org, 'test', '{}')"
                ),
                {"org": contoso.id},
            )
