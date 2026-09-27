"""HTTP contracts for route and error paths outside the invoice happy path."""

import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import document_service, review_service
from app.db import get_session
from app.document_service import (
    DocumentLimitReached,
    InvalidDocument,
    MissingWorkflowConfig,
)
from app.main import app, current_session
from app.storage import StorageError, get_store


@pytest.fixture(autouse=True)
def clear_route_overrides() -> Any:
    """Keep endpoint dependency substitutions local to each contract test."""
    try:
        yield
    finally:
        app.dependency_overrides.pop(current_session, None)
        app.dependency_overrides.pop(get_store, None)
        app.dependency_overrides.pop(get_session, None)


@pytest.mark.parametrize(
    ("method", "path", "kwargs"),
    [
        ("GET", "/v1/auth/me", {}),
        ("GET", "/v1/organization/members", {}),
        ("GET", "/v1/documents", {}),
        ("GET", f"/v1/documents/{uuid.uuid4()}", {}),
        ("GET", f"/v1/documents/{uuid.uuid4()}/file", {}),
        ("GET", f"/v1/documents/{uuid.uuid4()}/timeline", {}),
        ("GET", "/v1/review/queue", {}),
        ("POST", f"/v1/documents/{uuid.uuid4()}/retry", {}),
        (
            "POST",
            f"/v1/documents/{uuid.uuid4()}/fields/{uuid.uuid4()}",
            {"json": {"version": 0, "action": "accept"}},
        ),
        ("GET", "/v1/actions", {}),
        ("GET", f"/v1/actions/{uuid.uuid4()}", {}),
        (
            "POST",
            f"/v1/actions/{uuid.uuid4()}/decision",
            {"json": {"version": 0, "decision": "approve"}},
        ),
        ("POST", f"/v1/actions/{uuid.uuid4()}/retry", {"json": {"version": 0}}),
        ("GET", "/v1/settings/policies", {}),
        ("POST", "/v1/settings/policies", {"json": {"version": 0}}),
        ("GET", "/v1/settings/connectors", {}),
        ("GET", "/v1/settings/workflow", {}),
        ("GET", f"/v1/exports?connector_id={uuid.uuid4()}", {}),
        ("GET", f"/v1/exports/{uuid.uuid4()}/2026-09.csv", {}),
        (
            "POST",
            "/v1/documents",
            {"files": {"file": ("invoice.pdf", b"%PDF-test", "application/pdf")}},
        ),
    ],
)
def test_protected_routes_require_a_session(method: str, path: str, kwargs: dict[str, Any]) -> None:
    app.dependency_overrides[get_store] = lambda: object()
    with TestClient(app) as client:
        response = client.request(method, path, **kwargs)
    assert response.status_code == 401
    assert response.json()["error"] == {
        "code": "unauthorized",
        "message": "Not authenticated",
        "details": None,
    }
    assert response.headers["x-request-id"]


def test_read_only_member_cannot_manage_documents_or_members(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    org_id = uuid.uuid4()
    app.dependency_overrides[current_session] = lambda: (
        object(),
        SimpleNamespace(id=uuid.uuid4()),
        SimpleNamespace(id=org_id),
        SimpleNamespace(role="viewer"),
    )
    app.dependency_overrides[get_store] = lambda: object()
    monkeypatch.setattr(document_service, "browse", lambda session, org, user, role, **kwargs: [])
    monkeypatch.setattr(
        review_service, "read_document", lambda session, org, document, user, role: None
    )

    denied_routes: list[tuple[str, str, dict[str, Any]]] = [
        ("GET", "/v1/organization/members", {}),
        ("GET", "/v1/settings/policies", {}),
        ("POST", "/v1/settings/policies", {"json": {"version": 0}}),
        ("GET", "/v1/settings/connectors", {}),
        (
            "POST",
            "/v1/settings/connectors",
            {"json": {"name": "x", "connector_type": "csv_export"}},
        ),
        ("GET", "/v1/settings/workflow", {}),
        ("POST", "/v1/settings/workflow", {"json": {"base_version": 0, "yaml": "a: 1"}}),
        ("GET", f"/v1/exports?connector_id={uuid.uuid4()}", {}),
        (
            "POST",
            "/v1/documents",
            {"files": {"file": ("invoice.pdf", b"%PDF-test", "application/pdf")}},
        ),
        ("POST", f"/v1/documents/{uuid.uuid4()}/retry", {}),
    ]
    with TestClient(app) as client:
        assert client.get("/v1/documents").json() == []
        assert client.get(f"/v1/documents/{uuid.uuid4()}").status_code == 404
        for method, path, kwargs in denied_routes:
            forbidden = client.request(method, path, **kwargs)
            assert forbidden.status_code == 403
            assert forbidden.json()["error"]["code"] == "forbidden"


def test_document_routes_reject_malformed_ids() -> None:
    app.dependency_overrides[current_session] = lambda: (
        object(),
        SimpleNamespace(id=uuid.uuid4()),
        SimpleNamespace(id=uuid.uuid4()),
        SimpleNamespace(role="admin"),
    )
    with TestClient(app) as client:
        for method, path in (
            ("GET", "/v1/documents/not-a-uuid"),
            ("POST", "/v1/documents/not-a-uuid/retry"),
        ):
            invalid = client.request(method, path)
            assert invalid.status_code == 422
            assert invalid.json()["error"]["code"] == "validation_error"
            assert any(
                item["field"] == "path.document_id" for item in invalid.json()["error"]["details"]
            )


@pytest.mark.parametrize(
    ("failure", "status_code"),
    [
        (InvalidDocument("Invalid PDF"), 400),
        (MissingWorkflowConfig("No workflow configuration"), 409),
        (DocumentLimitReached("Document limit reached"), 409),
        (StorageError("Object storage is unavailable"), 503),
    ],
)
def test_upload_returns_actionable_failure_status(
    monkeypatch: pytest.MonkeyPatch, failure: Exception, status_code: int
) -> None:
    app.dependency_overrides[current_session] = lambda: (
        object(),
        SimpleNamespace(id=uuid.uuid4()),
        SimpleNamespace(id=uuid.uuid4()),
        SimpleNamespace(role="admin"),
    )
    app.dependency_overrides[get_store] = lambda: object()

    def fail_upload(*args: Any) -> None:
        raise failure

    monkeypatch.setattr(document_service, "upload", fail_upload)
    with TestClient(app) as client:
        response = client.post(
            "/v1/documents",
            files={"file": ("invoice.pdf", b"%PDF-test", "application/pdf")},
        )
    assert response.status_code == status_code
    assert response.json()["error"]["message"] == str(failure)
    assert response.json()["error"]["details"] is None


def test_transient_database_conflicts_return_409_and_other_failures_500() -> None:
    from psycopg.errors import DeadlockDetected
    from sqlalchemy.exc import OperationalError

    def deadlocked() -> None:
        raise OperationalError("UPDATE actions", {}, DeadlockDetected())

    app.dependency_overrides[current_session] = deadlocked
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/v1/actions", headers={"X-Request-ID": "deadlock-1"})
    assert response.status_code == 409
    assert response.json()["error"] == {"code": "conflict", "message": "Try again", "details": None}
    assert response.headers["x-request-id"] == "deadlock-1"

    def broken() -> None:
        raise OperationalError("SELECT 1", {}, Exception("connection refused"))

    app.dependency_overrides[current_session] = broken
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/v1/actions")
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert "connection refused" not in response.text
