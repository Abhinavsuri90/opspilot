"""Text embeddings for memory retrieval.

The default embedder needs no external model: tokens and token bigrams are feature-hashed
into 256 dimensions with a signed hashing trick and L2-normalized, so cosine similarity
between two texts rewards shared vocabulary and phrasing. It is deterministic across
processes (BLAKE2 rather than Python's salted ``hash``). An OpenAI-compatible endpoint
can replace it behind the same interface; those calls are metered like any other model
call and respect the organization's daily budget.
"""

from __future__ import annotations

import hashlib
import logging
import math
import re
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from time import perf_counter
from typing import Protocol

import httpx

from app.learning_models import EMBEDDING_DIMENSIONS
from app.llm import pricing
from app.llm.client import CallOutcome, Recorder, describe_error, record_to_database

logger = logging.getLogger(__name__)
_TOKEN = re.compile(r"[a-z0-9]+")
MAX_TOKENS = 4000
MAX_REMOTE_CHARS = 8000


class Embedder(Protocol):
    name: str

    def embed(
        self,
        text: str,
        *,
        org_id: uuid.UUID | None,
        document_id: uuid.UUID | None,
        trace_id: str | None,
    ) -> list[float] | None: ...


def tokenize(text: str) -> list[str]:
    return _TOKEN.findall(text.casefold())[:MAX_TOKENS]


def _bucket(feature: str) -> tuple[int, float]:
    digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
    value = int.from_bytes(digest, "big")
    return value % EMBEDDING_DIMENSIONS, 1.0 if value >> 63 else -1.0


def hash_embedding(text: str) -> list[float]:
    """Signed feature hashing of unigrams and bigrams, L2-normalized; zeros for empty text."""
    vector = [0.0] * EMBEDDING_DIMENSIONS
    tokens = tokenize(text)
    bigrams = [f"{first} {second}" for first, second in zip(tokens, tokens[1:], strict=False)]
    features = tokens + bigrams
    for feature in features:
        index, sign = _bucket(feature)
        vector[index] += sign
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return vector
    return [value / norm for value in vector]


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)


class LocalHashEmbedder:
    """Deterministic, free and always available; never recorded in the ledger."""

    name = "local-hash"

    def embed(
        self,
        text: str,
        *,
        org_id: uuid.UUID | None,
        document_id: uuid.UUID | None,
        trace_id: str | None,
    ) -> list[float] | None:
        return hash_embedding(text)


class RemoteEmbedder:
    """An OpenAI-compatible ``/embeddings`` endpoint reduced to 256 dimensions.

    ``allow_paid_call`` is the organization's daily budget check; when it refuses, or the
    endpoint fails, ``embed`` returns ``None`` and the caller keeps working without the
    vector (a few-shot without an embedding is still found by vendor match).
    """

    name = "openai-compatible"

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str | None,
        *,
        client: httpx.Client | None = None,
        recorder: Recorder = record_to_database,
        allow_paid_call: Callable[[uuid.UUID], bool] | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.client = client or httpx.Client(timeout=20)
        self.recorder = recorder
        self.allow_paid_call = allow_paid_call

    def embed(
        self,
        text: str,
        *,
        org_id: uuid.UUID | None,
        document_id: uuid.UUID | None,
        trace_id: str | None,
    ) -> list[float] | None:
        if org_id is not None and self.allow_paid_call is not None:
            if not self.allow_paid_call(org_id):
                logger.info("Embedding skipped: daily model budget reached for org %s", org_id)
                return None
        started = perf_counter()
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        tokens_in: int | None = None
        try:
            response = self.client.post(
                f"{self.base_url}/embeddings",
                headers=headers,
                json={
                    "model": self.model,
                    "input": text[:MAX_REMOTE_CHARS],
                    "dimensions": EMBEDDING_DIMENSIONS,
                },
            )
            response.raise_for_status()
            body = response.json()
            values = body["data"][0]["embedding"]
            usage = body.get("usage") if isinstance(body, dict) else None
            if isinstance(usage, dict) and isinstance(usage.get("prompt_tokens"), int):
                tokens_in = int(usage["prompt_tokens"])
            if not isinstance(values, list) or len(values) != EMBEDDING_DIMENSIONS:
                raise ValueError(f"Embedding does not have {EMBEDDING_DIMENSIONS} dimensions")
            vector = [float(value) for value in values]
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
            self._record(org_id, document_id, trace_id, started, None, False, describe_error(exc))
            logger.warning("Embedding call failed: %s", describe_error(exc))
            return None
        self._record(org_id, document_id, trace_id, started, tokens_in, True, None)
        return vector

    def _record(
        self,
        org_id: uuid.UUID | None,
        document_id: uuid.UUID | None,
        trace_id: str | None,
        started: float,
        tokens_in: int | None,
        ok: bool,
        error: str | None,
    ) -> None:
        self.recorder(
            CallOutcome(
                purpose="embedding",
                provider=self.name,
                model=self.model,
                prompt_version="embedding-v1",
                org_id=org_id,
                document_id=document_id,
                trace_id=trace_id,
                tokens_in=tokens_in,
                tokens_out=0 if ok else None,
                cost_cents=pricing.cost_cents(self.name, self.model, tokens_in, 0) if ok else None,
                latency_ms=int((perf_counter() - started) * 1000),
                ok=ok,
                error=error,
                created_at=datetime.now(UTC),
            )
        )
