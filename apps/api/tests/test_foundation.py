import logging
import os
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import DBAPIError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.client_ip import client_ip, is_trusted_peer
from app.db import SessionLocal, get_session, normalize_database_url, set_org_context
from app.login_throttle import client_ip_hash, identity_hash
from app.main import app
from app.models import LoginAttempt, Membership, Organization
from tests.conftest import TEST_CLIENT_HOST, postgres


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


def test_unhandled_error_logs_request_id_and_completion_line(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def broken_dependency() -> None:
        raise RuntimeError("private database detail")

    app.dependency_overrides[get_session] = broken_dependency
    try:
        with (
            caplog.at_level(logging.INFO, logger="uvicorn.error.opspilot"),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            failed = client.get("/readyz", headers={"X-Request-ID": "failure-log-123"})
    finally:
        del app.dependency_overrides[get_session]
    assert failed.status_code == 500
    assert failed.headers["x-request-id"] == "failure-log-123"
    messages = [
        record.getMessage() for record in caplog.records if record.name == "uvicorn.error.opspilot"
    ]
    assert any("Unhandled API error request_id=failure-log-123" in item for item in messages)
    completion = [item for item in messages if item.startswith("request_complete")]
    assert completion and "status=500" in completion[-1]
    assert "request_id=failure-log-123" in completion[-1]
    assert "private database detail" not in failed.text


def test_browser_post_rejects_untrusted_origin() -> None:
    with TestClient(app) as client:
        forbidden = client.post(
            "/v1/auth/login",
            json={},
            headers={"Origin": "https://malicious.example", "X-Request-ID": "origin-123"},
        )
        assert forbidden.status_code == 403
        assert forbidden.json()["error"]["code"] == "forbidden"
        assert forbidden.headers["x-request-id"] == "origin-123"

        fetch_forbidden = client.post(
            "/v1/auth/login", json={}, headers={"Sec-Fetch-Site": "cross-site"}
        )
        assert fetch_forbidden.status_code == 403

        # API clients without Origin remain supported.
        assert client.post("/v1/auth/login", json={}).status_code == 422


def test_upload_request_body_is_capped_before_multipart_parsing() -> None:
    from app.limits import MAX_UPLOAD_REQUEST_BYTES

    with TestClient(app) as client:
        oversized = client.post(
            "/v1/documents",
            content=b"x" * (MAX_UPLOAD_REQUEST_BYTES + 1),
            headers={"Content-Type": "application/octet-stream", "X-Request-ID": "too-large-123"},
        )
        assert oversized.status_code == 413
        assert oversized.json()["error"]["code"] == "upload_too_large"
        assert oversized.headers["x-request-id"] == "too-large-123"

        streamed = client.post(
            "/v1/documents",
            content=iter([b"x" * MAX_UPLOAD_REQUEST_BYTES, b"x"]),
            headers={"Transfer-Encoding": "chunked"},
        )
        assert streamed.status_code == 413

        # A small body continues to authentication rather than being rejected.
        assert client.post("/v1/documents", content=b"x").status_code == 401


def test_readyz_fails_when_schema_is_missing() -> None:
    class MissingSchemaSession:
        def execute(self, statement: object) -> None:
            assert "login_attempts" in str(statement)
            raise SQLAlchemyError("missing table")

    app.dependency_overrides[get_session] = lambda: MissingSchemaSession()
    try:
        with TestClient(app) as client:
            response = client.get("/readyz")
        assert response.status_code == 503
        assert response.json()["error"]["message"] == "Database schema is not ready"
    finally:
        del app.dependency_overrides[get_session]


def test_readyz_fails_without_storage_bucket(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.main.settings", SimpleNamespace(s3_bucket=""))
    with TestClient(app) as client:
        response = client.get("/readyz")
    assert response.status_code == 503
    assert response.json()["error"]["message"] == "Object storage is not configured"


@pytest.mark.skipif("DATABASE_OWNER_URL" not in os.environ, reason="Postgres integration test")
def test_login_and_tenant_isolation() -> None:
    owner_engine = create_engine(normalize_database_url(os.environ["DATABASE_OWNER_URL"]))
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
        logout = client.post("/v1/auth/logout")
        assert logout.status_code == 204
        assert client.get("/v1/auth/me").status_code == 401

        client.cookies.set("opspilot_session", "forged-token")
        assert client.get("/v1/auth/me").status_code == 401

    app_engine = create_engine(normalize_database_url(os.environ["DATABASE_URL"]))
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


@pytest.mark.skipif("DATABASE_OWNER_URL" not in os.environ, reason="Postgres integration test")
def test_tenant_context_expires_at_transaction_end() -> None:
    owner_engine = create_engine(normalize_database_url(os.environ["DATABASE_OWNER_URL"]))
    with Session(owner_engine) as owner:
        northwind = owner.scalar(select(Organization).where(Organization.slug == "northwind"))
        contoso = owner.scalar(select(Organization).where(Organization.slug == "contoso"))
        assert northwind is not None and contoso is not None

    app_engine = create_engine(normalize_database_url(os.environ["DATABASE_URL"]))
    with Session(app_engine) as session:
        # An app connection without a transaction-local tenant cannot read memberships.
        assert session.scalars(select(Membership)).all() == []
        session.rollback()

        set_org_context(session, northwind.id)
        assert all(row.org_id == northwind.id for row in session.scalars(select(Membership)))
        session.rollback()

        # Reusing the Session must not retain Northwind's setting or rows.
        assert session.scalars(select(Membership)).all() == []
        session.rollback()

        set_org_context(session, contoso.id)
        visible = session.scalars(select(Membership)).all()
        assert visible and all(row.org_id == contoso.id for row in visible)


@pytest.mark.skipif("DATABASE_OWNER_URL" not in os.environ, reason="Postgres integration test")
def test_login_throttle_blocks_repeated_guesses_and_resets_after_success() -> None:
    import uuid

    from app.db import SessionLocal

    unknown_email = f"absent-{uuid.uuid4().hex}@example.com"
    with TestClient(app) as client:
        for _ in range(10):
            failed = client.post(
                "/v1/auth/login",
                json={
                    "org_slug": "northwind",
                    "email": unknown_email,
                    "password": "wrong-password",
                },
            )
            assert failed.status_code == 401
        blocked = client.post(
            "/v1/auth/login",
            json={"org_slug": "northwind", "email": unknown_email, "password": "wrong-password"},
        )
        assert blocked.status_code == 429
        with SessionLocal() as session:
            row = session.get(LoginAttempt, identity_hash("northwind", unknown_email))
            assert row is not None and row.attempts == 11
        with SessionLocal() as session, session.begin():
            row = session.get(LoginAttempt, identity_hash("northwind", unknown_email))
            assert row is not None
            row.window_started_at = datetime.now(UTC) - timedelta(minutes=16)
        after_window = client.post(
            "/v1/auth/login",
            json={"org_slug": "northwind", "email": unknown_email, "password": "wrong-password"},
        )
        assert after_window.status_code == 401
        with SessionLocal() as session:
            row = session.get(LoginAttempt, identity_hash("northwind", unknown_email))
            assert row is not None and row.attempts == 1

        known_email = "northwind@example.com"
        for _ in range(2):
            assert client.post(
                "/v1/auth/login",
                json={
                    "org_slug": "northwind",
                    "email": known_email,
                    "password": "wrong-password",
                },
            ).status_code == 401
        success = client.post(
            "/v1/auth/login",
            json={
                "org_slug": "northwind",
                "email": known_email,
                "password": os.environ["DEMO_PASSWORD"],
            },
        )
        assert success.status_code == 200
        with SessionLocal() as session:
            assert session.get(LoginAttempt, identity_hash("northwind", known_email)) is None


@postgres
def test_readyz_reports_ready_with_migrated_schema() -> None:
    with TestClient(app) as client:
        response = client.get("/readyz")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


@postgres
def test_login_throttle_limits_attempts_per_client_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.login_throttle.MAX_IP_ATTEMPTS_PER_WINDOW", 3)
    with TestClient(app) as client:
        for _ in range(3):
            guess = client.post(
                "/v1/auth/login",
                json={
                    "org_slug": "northwind",
                    "email": f"absent-{uuid.uuid4().hex}@example.com",
                    "password": "wrong-password",
                },
            )
            assert guess.status_code == 401
        blocked = client.post(
            "/v1/auth/login",
            json={
                "org_slug": "northwind",
                "email": f"absent-{uuid.uuid4().hex}@example.com",
                "password": "wrong-password",
            },
        )
        assert blocked.status_code == 429
        # Even correct credentials stay blocked until the address window resets.
        assert (
            client.post(
                "/v1/auth/login",
                json={
                    "org_slug": "northwind",
                    "email": "northwind@example.com",
                    "password": os.environ["DEMO_PASSWORD"],
                },
            ).status_code
            == 429
        )
        with SessionLocal() as session:
            row = session.get(LoginAttempt, client_ip_hash(TEST_CLIENT_HOST))
            assert row is not None and row.attempts == 5
            # The per-account counter for the demo user is unaffected by the address block.
            account = session.get(LoginAttempt, identity_hash("northwind", "northwind@example.com"))
            assert account is not None and account.attempts == 1
        with SessionLocal() as session, session.begin():
            row = session.get(LoginAttempt, client_ip_hash(TEST_CLIENT_HOST))
            assert row is not None
            row.window_started_at = datetime.now(UTC) - timedelta(minutes=16)
        success = client.post(
            "/v1/auth/login",
            json={
                "org_slug": "northwind",
                "email": "northwind@example.com",
                "password": os.environ["DEMO_PASSWORD"],
            },
        )
        assert success.status_code == 200
        with SessionLocal() as session:
            account_key = identity_hash("northwind", "northwind@example.com")
            assert session.get(LoginAttempt, account_key) is None
            row = session.get(LoginAttempt, client_ip_hash(TEST_CLIENT_HOST))
            assert row is not None and row.attempts == 1


def test_request_timing_and_json_body_limit() -> None:
    with TestClient(app) as client:
        health = client.get("/healthz", headers={"X-Request-ID": "timing-check"})
        assert health.status_code == 200
        assert health.headers["server-timing"].startswith("api;dur=")
        assert float(health.headers["server-timing"].split("=")[1]) >= 0
        assert health.headers["x-request-id"] == "timing-check"
        oversized = client.post(
            "/v1/auth/register-organization",
            content=b"x" * (64 * 1024 + 1),
            headers={"content-type": "application/json"},
        )
        assert oversized.status_code == 413
        assert oversized.json()["error"]["code"] == "request_too_large"


def fake_request(peer: str | None, forwarded: str | None = None) -> Any:
    headers = {"x-forwarded-for": forwarded} if forwarded is not None else {}
    return SimpleNamespace(
        client=SimpleNamespace(host=peer) if peer is not None else None, headers=headers
    )


@pytest.mark.parametrize(
    ("peer", "forwarded", "expected"),
    [
        ("10.0.0.5", "1.2.3.4", "1.2.3.4"),
        ("127.0.0.1", "9.9.9.9, 1.2.3.4", "1.2.3.4"),
        ("172.16.8.1", " 5.5.5.5 ,  6.6.6.6 , ", "6.6.6.6"),
        ("192.168.1.2", "", "192.168.1.2"),
        ("192.168.1.2", None, "192.168.1.2"),
        ("::1", "2001:db8::10", "2001:db8::10"),
        ("fd12::1", "2001:db8::10", "2001:db8::10"),
        ("203.0.113.7", "1.2.3.4", "203.0.113.7"),
        ("203.0.113.7", None, "203.0.113.7"),
        ("testclient", "1.2.3.4", "testclient"),
        (None, "1.2.3.4", "unknown"),
        ("", "1.2.3.4", "unknown"),
    ],
)
def test_client_ip_trusts_only_the_edge_appended_forwarded_entry(
    peer: str | None, forwarded: str | None, expected: str
) -> None:
    assert client_ip(fake_request(peer, forwarded)) == expected


def test_trusted_peer_recognizes_loopback_and_private_ranges_only() -> None:
    assert all(is_trusted_peer(host) for host in ("127.0.0.1", "10.1.2.3", "172.31.0.9", "::1"))
    assert all(is_trusted_peer(host) for host in ("192.168.0.1", "fc00::1", "fdff::2"))
    assert is_trusted_peer("::ffff:10.0.0.7")
    public = ("8.8.8.8", "172.32.0.1", "203.0.113.7", "100.64.0.1", "169.254.1.1", "2001:db8::1")
    assert not any(is_trusted_peer(host) for host in public)
    assert not is_trusted_peer("") and not is_trusted_peer("not-an-address")


def test_login_throttle_keys_on_trusted_forwarded_address(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    def record(session: object, org_slug: str, email: str, address: str) -> bool:
        seen.append(address)
        return False

    monkeypatch.setattr("app.main.reserve_login", record)
    app.dependency_overrides[get_session] = lambda: object()
    try:
        with TestClient(app) as client:
            # TestClient's peer "testclient" is not an address, so the header is ignored.
            spoofed = client.post(
                "/v1/auth/login",
                json={"org_slug": "northwind", "email": "a@example.com", "password": "x"},
                headers={"X-Forwarded-For": "1.2.3.4"},
            )
            assert spoofed.status_code == 429
    finally:
        del app.dependency_overrides[get_session]
    assert seen == ["testclient"]
