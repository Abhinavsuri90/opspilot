"""HMAC-signed JSON webhook. Receivers verify ``X-OpsPilot-Signature`` and dedupe on
``X-OpsPilot-Idempotency-Key``."""

import hashlib
import hmac
import json
import logging
import re
import time
from collections.abc import Callable
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.connectors.base import (
    ActionRequest,
    ConnectionTest,
    Diff,
    ExecutionResult,
)
from app.connectors.network import DestinationBlocked, check_destination

logger = logging.getLogger(__name__)
REQUEST_TIMEOUT_SECONDS = 10.0
RETRYABLE_STATUSES = frozenset({408, 429})
_HEADER_NAME = re.compile(r"^[A-Za-z0-9-]{1,64}$")
_RESERVED_HEADERS = frozenset(
    {"host", "content-length", "content-type", "transfer-encoding", "connection"}
)


class WebhookConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    url: str = Field(min_length=8, max_length=2000)
    # Static headers such as a tenant identifier. Secrets belong in the credential secret,
    # which signs every request, not here.
    headers: dict[str, str] = Field(default_factory=dict, max_length=20)

    @field_validator("url")
    @classmethod
    def check_url(cls, value: str) -> str:
        try:
            check_destination(value)
        except DestinationBlocked as exc:
            raise ValueError(str(exc)) from exc
        return value

    @field_validator("headers")
    @classmethod
    def check_headers(cls, value: dict[str, str]) -> dict[str, str]:
        for name, header in value.items():
            if not _HEADER_NAME.fullmatch(name):
                raise ValueError(f"Header name is invalid: {name!r}")
            lowered = name.lower()
            if lowered in _RESERVED_HEADERS or lowered.startswith("x-opspilot-"):
                raise ValueError(f"Header {name} is set by the connector and cannot be overridden")
            if len(header) > 1000 or any(char in header for char in "\r\n\0"):
                raise ValueError(f"Header value for {name} is invalid")
        return value


class WebhookCredentials(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    secret: str = Field(min_length=16, max_length=512)


def sign(secret: str, timestamp: str, body: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), f"{timestamp}.{body}".encode(), hashlib.sha256)
    return "sha256=" + digest.hexdigest()


def canonical_body(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def default_client() -> httpx.Client:
    return httpx.Client(timeout=httpx.Timeout(REQUEST_TIMEOUT_SECONDS), follow_redirects=False)


class WebhookConnector:
    type_name = "webhook"
    config_model = WebhookConfig
    credentials_model: type[BaseModel] | None = WebhookCredentials

    def __init__(self, client_factory: Callable[[], httpx.Client] = default_client) -> None:
        self._client_factory = client_factory

    def describe_capabilities(self) -> dict[str, Any]:
        return {
            "action_types": ["post_webhook"],
            "signature": "X-OpsPilot-Signature: sha256=HMAC_SHA256(secret, timestamp + '.' + body)",
            "idempotency": "X-OpsPilot-Idempotency-Key header; the receiver deduplicates",
            "retryable_statuses": "408, 429 and 5xx",
        }

    def _post(
        self, config: dict[str, Any], secret: str, payload: dict[str, Any], idempotency_key: str
    ) -> httpx.Response:
        body = canonical_body(payload)
        timestamp = str(int(time.time()))
        headers = {
            **{str(k): str(v) for k, v in dict(config.get("headers") or {}).items()},
            "Content-Type": "application/json",
            "User-Agent": "OpsPilot-Webhook/1",
            "X-OpsPilot-Timestamp": timestamp,
            "X-OpsPilot-Idempotency-Key": idempotency_key,
            "X-OpsPilot-Signature": sign(secret, timestamp, body),
        }
        with self._client_factory() as client:
            return client.post(str(config["url"]), content=body.encode("utf-8"), headers=headers)

    def test_connection(
        self, config: dict[str, Any], credentials: dict[str, Any] | None
    ) -> ConnectionTest:
        secret = str((credentials or {}).get("secret", ""))
        if not secret:
            return ConnectionTest(False, "Webhook secret is missing")
        try:
            check_destination(str(config["url"]))
            response = self._post(
                config, secret, {"type": "test", "sent_at": int(time.time())}, "test"
            )
        except DestinationBlocked as exc:
            return ConnectionTest(False, str(exc))
        except httpx.HTTPError as exc:
            return ConnectionTest(False, f"Request failed: {type(exc).__name__}")
        if 200 <= response.status_code < 300:
            return ConnectionTest(True, f"HTTP {response.status_code}")
        return ConnectionTest(False, f"HTTP {response.status_code}")

    def preview(self, config: dict[str, Any], request: ActionRequest) -> Diff:
        body = self._payload(request)
        return Diff(
            kind="post_webhook",
            title=f"POST {config['url']}",
            before=None,
            after=body,
            lines=[f"POST {config['url']}", "Signed with HMAC-SHA256"]
            + [f"{column}: {value}" for column, value in request.values.items()],
        )

    def _payload(self, request: ActionRequest) -> dict[str, Any]:
        return {
            "action_id": str(request.action_id),
            "document_id": str(request.document_id),
            "action_type": request.action_type,
            "payload": dict(request.values),
            "proposed_at": request.proposed_at.isoformat(),
        }

    def execute(
        self,
        config: dict[str, Any],
        credentials: dict[str, Any] | None,
        request: ActionRequest,
        idempotency_key: str,
    ) -> ExecutionResult:
        secret = str((credentials or {}).get("secret", ""))
        if not secret:
            return ExecutionResult(False, None, "Webhook secret is missing", retryable=False)
        try:
            # Re-check at send time: DNS may have changed since the URL was saved.
            check_destination(str(config["url"]))
            response = self._post(config, secret, self._payload(request), idempotency_key)
        except DestinationBlocked as exc:
            return ExecutionResult(False, None, str(exc), retryable=False)
        except httpx.TimeoutException:
            return ExecutionResult(False, None, "Request timed out", retryable=True)
        except httpx.HTTPError as exc:
            return ExecutionResult(
                False, None, f"Request failed: {type(exc).__name__}", retryable=True
            )
        summary = describe_response(response)
        if 200 <= response.status_code < 300:
            return ExecutionResult(True, external_id_of(response), summary, retryable=False)
        retryable = response.status_code in RETRYABLE_STATUSES or response.status_code >= 500
        logger.info(
            "Webhook action %s got HTTP %s (retryable=%s)",
            request.action_id,
            response.status_code,
            retryable,
        )
        return ExecutionResult(False, None, summary, retryable=retryable)


def describe_response(response: httpx.Response) -> str:
    """Status, content type and size only; the body may echo the payload."""
    content_type = response.headers.get("content-type", "").split(";")[0].strip() or "no body"
    return f"HTTP {response.status_code} ({content_type}, {len(response.content)} bytes)"


def external_id_of(response: httpx.Response) -> str | None:
    if "json" not in response.headers.get("content-type", ""):
        return None
    try:
        body = response.json()
    except ValueError:
        return None
    if isinstance(body, dict):
        identifier = body.get("id")
        if isinstance(identifier, str | int) and len(str(identifier)) <= 200:
            return str(identifier)
    return None
