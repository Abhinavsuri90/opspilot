"""The one path every model call takes, and the ledger row each call leaves behind.

``call_chat`` sends a structured-output chat request through a :class:`ChatBackend` and
records an ``llm_calls`` row whether the call succeeded or failed, with the cost from
``app.llm.pricing``. Deterministic providers (rules, mock) go through ``record_local_call``
so their runs appear in the same ledger at zero cost. Recording is best effort: a ledger
write that fails is logged and never turns a successful extraction into a failure.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from time import perf_counter
from typing import Any, Literal, Protocol

import httpx

from app.db import SessionLocal, set_org_context
from app.learning_models import LlmCall
from app.llm import pricing

logger = logging.getLogger(__name__)
Purpose = Literal["extraction", "escalation", "embedding", "agent"]
Message = dict[str, str]
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MAX_ERROR_LENGTH = 300


class ProviderUnavailable(Exception):
    pass


@dataclass(frozen=True)
class CallOutcome:
    """What the ledger stores about one call; ``document_id`` is null for eval runs."""

    purpose: str
    provider: str
    model: str
    prompt_version: str
    org_id: uuid.UUID | None
    document_id: uuid.UUID | None
    trace_id: str | None
    tokens_in: int | None
    tokens_out: int | None
    cost_cents: Decimal | None
    latency_ms: int
    ok: bool
    error: str | None
    created_at: datetime


Recorder = Callable[[CallOutcome], None]


@dataclass(frozen=True)
class Completion:
    """A backend's raw answer: the message content plus token usage when reported."""

    content: str
    tokens_in: int | None
    tokens_out: int | None


@dataclass(frozen=True)
class ChatResult:
    content: str
    decoded: Any
    model: str
    tokens_in: int | None
    tokens_out: int | None
    cost_cents: Decimal | None
    latency_ms: int


class ChatBackend(Protocol):
    name: str

    def complete(
        self,
        model: str,
        messages: list[Message],
        schema: dict[str, Any] | None,
        *,
        schema_name: str,
        max_tokens: int,
    ) -> Completion: ...


class OpenRouterBackend:
    """Structured JSON output from OpenRouter's chat completions endpoint."""

    name = "openrouter"

    def __init__(self, api_key: str, client: httpx.Client | None = None) -> None:
        self.api_key = api_key
        self.client = client or httpx.Client(timeout=45)

    def complete(
        self,
        model: str,
        messages: list[Message],
        schema: dict[str, Any] | None,
        *,
        schema_name: str,
        max_tokens: int,
    ) -> Completion:
        payload: dict[str, Any] = {
            "model": model,
            "temperature": 0,
            "max_tokens": max_tokens,
            "provider": {"require_parameters": True},
            "messages": messages,
        }
        if schema is not None:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": schema_name, "strict": True, "schema": schema},
            }
        response = self.client.post(
            OPENROUTER_URL, headers={"Authorization": f"Bearer {self.api_key}"}, json=payload
        )
        response.raise_for_status()
        body = response.json()
        content = body["choices"][0]["message"]["content"]
        if not isinstance(content, str):
            raise ValueError("Message content is not text")
        usage = body.get("usage") if isinstance(body, dict) else None
        return Completion(
            content,
            _token_count(usage, "prompt_tokens"),
            _token_count(usage, "completion_tokens"),
        )


def _token_count(usage: object, key: str) -> int | None:
    if isinstance(usage, dict):
        value = usage.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            return value
    return None


def _elapsed_ms(started: float) -> int:
    return int((perf_counter() - started) * 1000)


def describe_error(exc: BaseException) -> str:
    """A short, document-free description: the exception type and, for HTTP, the status."""
    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTP {exc.response.status_code}"[:MAX_ERROR_LENGTH]
    if isinstance(exc, httpx.HTTPError):
        return type(exc).__name__[:MAX_ERROR_LENGTH]
    text = str(exc).strip()
    label = type(exc).__name__
    return (f"{label}: {text}" if text else label)[:MAX_ERROR_LENGTH]


def record_to_database(outcome: CallOutcome) -> None:
    """Default recorder: one short transaction under the owning tenant's RLS context."""
    if outcome.org_id is None:
        logger.debug("Model call outside a tenant context is not recorded")
        return
    try:
        with SessionLocal() as session, session.begin():
            set_org_context(session, outcome.org_id)
            session.add(row_for(outcome))
    except Exception:
        logger.exception("Could not record the model call ledger row")


def row_for(outcome: CallOutcome) -> LlmCall:
    return LlmCall(
        id=uuid.uuid4(),
        org_id=outcome.org_id,
        document_id=outcome.document_id,
        purpose=outcome.purpose,
        provider=outcome.provider,
        model=outcome.model,
        prompt_version=outcome.prompt_version,
        tokens_in=outcome.tokens_in,
        tokens_out=outcome.tokens_out,
        cost_cents=outcome.cost_cents,
        latency_ms=outcome.latency_ms,
        ok=outcome.ok,
        error=outcome.error,
        trace_id=outcome.trace_id,
        created_at=outcome.created_at,
    )


def call_chat(
    purpose: Purpose,
    messages: list[Message],
    schema: dict[str, Any] | None,
    model: str,
    org_id: uuid.UUID | None,
    document_id: uuid.UUID | None,
    trace_id: str | None,
    *,
    backend: ChatBackend,
    prompt_version: str,
    recorder: Recorder = record_to_database,
    schema_name: str = "document_fields",
    max_tokens: int = 1200,
) -> ChatResult:
    """Run one chat completion, record it, and return the parsed JSON content.

    Raises :class:`ProviderUnavailable` after recording a failed row when the backend
    errors or returns something that is not valid JSON.
    """
    started = perf_counter()
    try:
        completion = backend.complete(
            model, messages, schema, schema_name=schema_name, max_tokens=max_tokens
        )
        decoded = json.loads(completion.content)
    except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
        recorder(
            CallOutcome(
                purpose=purpose,
                provider=backend.name,
                model=model,
                prompt_version=prompt_version,
                org_id=org_id,
                document_id=document_id,
                trace_id=trace_id,
                tokens_in=None,
                tokens_out=None,
                cost_cents=None,
                latency_ms=_elapsed_ms(started),
                ok=False,
                error=describe_error(exc),
                created_at=datetime.now(UTC),
            )
        )
        raise ProviderUnavailable(
            f"{backend.name} did not return valid structured output"
        ) from exc
    latency_ms = _elapsed_ms(started)
    cost = pricing.cost_cents(backend.name, model, completion.tokens_in, completion.tokens_out)
    recorder(
        CallOutcome(
            purpose=purpose,
            provider=backend.name,
            model=model,
            prompt_version=prompt_version,
            org_id=org_id,
            document_id=document_id,
            trace_id=trace_id,
            tokens_in=completion.tokens_in,
            tokens_out=completion.tokens_out,
            cost_cents=cost,
            latency_ms=latency_ms,
            ok=True,
            error=None,
            created_at=datetime.now(UTC),
        )
    )
    return ChatResult(
        content=completion.content,
        decoded=decoded,
        model=model,
        tokens_in=completion.tokens_in,
        tokens_out=completion.tokens_out,
        cost_cents=cost,
        latency_ms=latency_ms,
    )


def record_local_call(
    purpose: Purpose,
    provider: str,
    model: str,
    prompt_version: str,
    org_id: uuid.UUID | None,
    document_id: uuid.UUID | None,
    trace_id: str | None,
    *,
    latency_ms: int,
    ok: bool,
    error: str | None = None,
    recorder: Recorder = record_to_database,
) -> None:
    """Ledger row for a deterministic provider: no tokens, zero cost, same shape."""
    recorder(
        CallOutcome(
            purpose=purpose,
            provider=provider,
            model=model,
            prompt_version=prompt_version,
            org_id=org_id,
            document_id=document_id,
            trace_id=trace_id,
            tokens_in=None,
            tokens_out=None,
            cost_cents=pricing.cost_cents(provider, model, None, None),
            latency_ms=latency_ms,
            ok=ok,
            error=error[:MAX_ERROR_LENGTH] if error else None,
            created_at=datetime.now(UTC),
        )
    )
