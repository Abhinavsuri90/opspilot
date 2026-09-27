from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.db import normalize_database_url
from app.storage import S3ObjectStore, StoredDocumentTooLarge


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (
            "postgres://user:pass@host:5432/db?sslmode=require",
            "postgresql+psycopg://user:pass@host:5432/db?sslmode=require",
        ),
        (
            "postgresql://user:pass@host/db",
            "postgresql+psycopg://user:pass@host/db",
        ),
        (
            "postgresql+psycopg://user:pass@host/db",
            "postgresql+psycopg://user:pass@host/db",
        ),
    ],
)
def test_normalize_database_url(url: str, expected: str) -> None:
    assert normalize_database_url(url) == expected


@pytest.mark.parametrize("style", ["auto", "path", "virtual"])
def test_s3_addressing_style_configures_client(
    monkeypatch: pytest.MonkeyPatch, style: str
) -> None:
    captured: dict[str, Any] = {}

    def fake_client(service_name: str, **kwargs: Any) -> object:
        captured.update(kwargs)
        assert service_name == "s3"
        return object()

    settings = SimpleNamespace(
        s3_bucket="test-documents",
        s3_endpoint_url="https://bucket.example.test",
        s3_region="us-east-1",
        s3_access_key_id="test-key",
        s3_secret_access_key="test-secret",
        s3_addressing_style=style,
    )
    monkeypatch.setattr("app.storage.get_settings", lambda: settings)
    monkeypatch.setattr("app.storage.boto3.client", fake_client)

    store = S3ObjectStore()
    assert store.bucket == "test-documents"
    assert captured["config"].s3["addressing_style"] == style


def test_invalid_s3_addressing_style_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, s3_addressing_style="unsupported")


def test_deployment_requires_remote_storage_configuration() -> None:
    valid: dict[str, Any] = {
        "environment": "staging",
        "jwt_secret": "s" * 40,
        "cookie_secure": True,
        "web_origin": "https://example.test",
        "database_url": "postgresql://opspilot_app:staging-pass@db.internal:5432/opspilot",
        "s3_bucket": "opspilot-staging-documents",
        "s3_region": "auto",
        "s3_endpoint_url": "https://bucket.example.test",
        "s3_access_key_id": "staging-key",
        "s3_secret_access_key": "staging-secret",
        "connector_encryption_key": "u2s5H8Zq1iJd0m9qF0O5v1uTn7fJbdxlN1eXKjKlY7E=",
    }
    assert Settings(_env_file=None, **valid).s3_bucket == "opspilot-staging-documents"
    for changed in (
        {"s3_bucket": "documents"},
        {"s3_access_key_id": "local"},
        {"s3_secret_access_key": "local"},
        {"s3_endpoint_url": "http://s3mock:9090"},
        {"s3_secret_access_key": ""},
        {"web_origin": "http://localhost:3300"},
        {"web_origin": "https://"},
        {"web_origin": "https://example.test/path"},
        {"web_origin": "https://example.test?next=bad"},
        {"web_origin": "https://user@example.test"},
        {"database_url": "postgresql://opspilot_app:pass@localhost:5432/opspilot"},
        {"database_url": "postgresql://opspilot_owner:pass@db.internal:5432/opspilot"},
        {"connector_encryption_key": None},
        {"connector_encryption_key": ""},
        {"connector_encryption_key": "not-a-fernet-key"},
    ):
        with pytest.raises(ValidationError):
            Settings(_env_file=None, **(valid | changed))
    # Development derives a local key instead of requiring one.
    assert Settings(_env_file=None, environment="development").connector_encryption_key is None
    bounded = Settings(_env_file=None, action_execute_timeout_seconds=120)
    assert bounded.action_execute_timeout_seconds == 120
    with pytest.raises(ValidationError):
        Settings(_env_file=None, action_execute_timeout_seconds=121)


def test_s3_read_is_bounded_and_closes_stream(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.limits import MAX_UPLOAD_BYTES

    class FakeBody:
        def __init__(self, data: bytes) -> None:
            self.data = data
            self.closed = False
            self.read_size: int | None = None

        def read(self, size: int) -> bytes:
            self.read_size = size
            return self.data[:size]

        def close(self) -> None:
            self.closed = True

    class FakeClient:
        def __init__(self, body: FakeBody, length: int | None = None) -> None:
            self.body = body
            self.length = length

        def get_object(self, **kwargs: Any) -> dict[str, Any]:
            response: dict[str, Any] = {"Body": self.body}
            if self.length is not None:
                response["ContentLength"] = self.length
            return response

    clients: list[FakeClient] = []

    def fake_client(service_name: str, **kwargs: Any) -> FakeClient:
        assert service_name == "s3"
        return clients[-1]

    monkeypatch.setattr("app.storage.boto3.client", fake_client)
    good = FakeBody(b"small PDF")
    clients.append(FakeClient(good))
    assert S3ObjectStore().get("document") == b"small PDF"
    assert good.read_size == MAX_UPLOAD_BYTES + 1 and good.closed

    too_large = FakeBody(b"")
    clients.append(FakeClient(too_large, MAX_UPLOAD_BYTES + 1))
    with pytest.raises(StoredDocumentTooLarge, match="exceeds"):
        S3ObjectStore().get("document")
    assert too_large.read_size is None and too_large.closed

    oversized_body = FakeBody(b"x" * (MAX_UPLOAD_BYTES + 1))
    clients.append(FakeClient(oversized_body))
    with pytest.raises(StoredDocumentTooLarge, match="exceeds"):
        S3ObjectStore().get("document")
    assert oversized_body.read_size == MAX_UPLOAD_BYTES + 1 and oversized_body.closed


def test_iam_credentials_can_use_default_chain(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_client(service_name: str, **kwargs: Any) -> object:
        captured.update(kwargs)
        assert service_name == "s3"
        return object()

    settings = SimpleNamespace(
        s3_bucket="aws-documents",
        s3_endpoint_url=None,
        s3_region="us-east-1",
        s3_access_key_id="",
        s3_secret_access_key="",
        s3_addressing_style="auto",
    )
    monkeypatch.setattr("app.storage.get_settings", lambda: settings)
    monkeypatch.setattr("app.storage.boto3.client", fake_client)
    S3ObjectStore()
    assert "aws_access_key_id" not in captured
    assert "aws_secret_access_key" not in captured


def test_settings_bound_timeouts_parse_cap_and_proxy_cidrs() -> None:
    bounded = Settings(_env_file=None, extraction_timeout_seconds=240)
    assert bounded.extraction_timeout_seconds == 240
    with pytest.raises(ValidationError):
        Settings(_env_file=None, extraction_timeout_seconds=241)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, max_concurrent_parses=0)
    with pytest.raises(ValidationError, match="not a CIDR"):
        Settings(_env_file=None, trusted_proxy_cidrs="10.0.0.0/8,nope")
    normalized = Settings(_env_file=None, trusted_proxy_cidrs=" 10.1.2.3/8 , ::1 ,")
    assert normalized.trusted_proxy_cidrs == "10.0.0.0/8,::1/128"
    assert Settings(_env_file=None, trusted_proxy_cidrs="").trusted_proxy_cidrs == ""
