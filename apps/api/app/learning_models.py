"""Learning-loop records: metered model calls and per-organization memory.

``llm_calls`` is the ledger every model call is written to (success and failure), which
the spend cap, the cost KPIs and the document timeline read. ``memory_items`` holds the
vendor profiles and few-shot examples that corrections produce; the ``embedding`` column
is a pgvector ``vector(256)`` on Postgres and JSON text under the SQLite test fixtures.
Design notes: docs/adr/009-learning-loop-and-router.md.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Dialect,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.dialects.postgresql.base import ischema_names
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import TypeDecorator, TypeEngine, UserDefinedType

from app.models import Base

EMBEDDING_DIMENSIONS = 256
CALL_PURPOSES = ("extraction", "escalation", "embedding", "agent")
MEMORY_KINDS = ("vendor_profile", "few_shot")


class Vector(UserDefinedType[list[float]]):
    """The pgvector column type; values travel as ``[x,y,...]`` text through psycopg."""

    cache_ok = True

    def __init__(self, dimensions: int = EMBEDDING_DIMENSIONS) -> None:
        self.dimensions = dimensions

    def get_col_spec(self, **kw: Any) -> str:
        return f"vector({self.dimensions})"


# Let reflection (the schema drift test, Alembic autogenerate) recognize pgvector columns.
ischema_names["vector"] = Vector


def encode_vector(values: list[float]) -> str:
    return "[" + ",".join(repr(float(value)) for value in values) + "]"


def decode_vector(raw: object) -> list[float] | None:
    if raw is None:
        return None
    if isinstance(raw, list | tuple):
        return [float(value) for value in raw]
    try:
        decoded = json.loads(str(raw))
    except ValueError:
        return None
    if not isinstance(decoded, list):
        return None
    return [float(value) for value in decoded]


class Embedding(TypeDecorator[list[float]]):
    """``vector(256)`` on Postgres, JSON text elsewhere, a Python list on both sides."""

    impl = Text
    cache_ok = True

    def load_dialect_impl(self, dialect: Dialect) -> TypeEngine[Any]:
        if dialect.name == "postgresql":
            return dialect.type_descriptor(Vector(EMBEDDING_DIMENSIONS))
        return dialect.type_descriptor(Text())

    def process_bind_param(self, value: list[float] | None, dialect: Dialect) -> str | None:
        if value is None:
            return None
        if len(value) != EMBEDDING_DIMENSIONS:
            raise ValueError(f"Embeddings must have {EMBEDDING_DIMENSIONS} dimensions")
        return encode_vector(value)

    def process_result_value(self, value: object, dialect: Dialect) -> list[float] | None:
        return decode_vector(value)


class LlmCall(Base):
    """One metered model call: extraction, escalation, embedding or agent step."""

    __tablename__ = "llm_calls"
    __table_args__ = (
        ForeignKeyConstraint(["org_id", "document_id"], ["documents.org_id", "documents.id"]),
        CheckConstraint(
            "purpose IN ('extraction', 'escalation', 'embedding', 'agent')",
            name="ck_llm_calls_purpose",
        ),
        Index("ix_llm_calls_org_created", "org_id", "created_at"),
        Index("ix_llm_calls_org_document", "org_id", "document_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    document_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    purpose: Mapped[str] = mapped_column(String(20), nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(50), nullable=False)
    tokens_in: Mapped[int | None] = mapped_column(Integer)
    tokens_out: Mapped[int | None] = mapped_column(Integer)
    # Null when the model has no entry in the price table; the KPIs count those separately.
    cost_cents: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    ok: Mapped[bool] = mapped_column(Boolean, nullable=False)
    error: Mapped[str | None] = mapped_column(String(300))
    trace_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MemoryItem(Base):
    """A vendor profile or a few-shot example; ``key`` is the normalized vendor name."""

    __tablename__ = "memory_items"
    __table_args__ = (
        CheckConstraint("kind IN ('vendor_profile', 'few_shot')", name="ck_memory_items_kind"),
        Index("ix_memory_items_org_kind_key", "org_id", "kind", "key"),
        Index(
            "uq_memory_items_vendor_profile",
            "org_id",
            "key",
            unique=True,
            postgresql_where=text("kind = 'vendor_profile'"),
            sqlite_where=text("kind = 'vendor_profile'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    key: Mapped[str] = mapped_column(String(200), nullable=False)
    content_json: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(Embedding())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# Re-exported so callers that only need the ledger's shape can avoid the ORM import cycle.
__all__ = [
    "CALL_PURPOSES",
    "EMBEDDING_DIMENSIONS",
    "MEMORY_KINDS",
    "Embedding",
    "LlmCall",
    "MemoryItem",
    "Vector",
    "decode_vector",
    "encode_vector",
]
