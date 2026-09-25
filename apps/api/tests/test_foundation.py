import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.db import set_org_context
from app.main import app
from app.models import Membership, Organization


def test_healthz() -> None:
    with TestClient(app) as client:
        response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["x-request-id"]


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
        login = client.post(
            "/v1/auth/login",
            json={
                "org_slug": "northwind",
                "email": "northwind@example.com",
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
