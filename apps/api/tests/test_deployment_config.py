from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.db import normalize_database_url
from app.storage import S3ObjectStore


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
    }
    assert Settings(_env_file=None, **valid).s3_bucket == "opspilot-staging-documents"
    for changed in (
        {"s3_bucket": "documents"},
        {"s3_access_key_id": "local"},
        {"s3_secret_access_key": "local"},
        {"s3_endpoint_url": "http://s3mock:9090"},
        {"s3_secret_access_key": ""},
        {"web_origin": "http://localhost:3300"},
        {"database_url": "postgresql://opspilot_app:pass@localhost:5432/opspilot"},
        {"database_url": "postgresql://opspilot_owner:pass@db.internal:5432/opspilot"},
    ):
        with pytest.raises(ValidationError):
            Settings(_env_file=None, **(valid | changed))


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
