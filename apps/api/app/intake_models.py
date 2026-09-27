"""Intake channel records: document links, API keys, email inboxes and processed messages."""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    true,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base

DOCUMENT_SOURCES = ("upload", "email", "api")
EMAIL_BACKENDS = ("imap", "mailpit")
LINK_KINDS = ("near_duplicate",)


class DocumentLink(Base):
    """A relation between two documents of one tenant; near duplicates are linked both ways."""

    __tablename__ = "document_links"
    __table_args__ = (
        ForeignKeyConstraint(["org_id", "document_id"], ["documents.org_id", "documents.id"]),
        ForeignKeyConstraint(
            ["org_id", "related_document_id"], ["documents.org_id", "documents.id"]
        ),
        UniqueConstraint(
            "org_id", "document_id", "related_document_id", "kind", name="uq_document_links_pair"
        ),
        CheckConstraint("kind IN ('near_duplicate')", name="ck_document_links_kind"),
        CheckConstraint("document_id <> related_document_id", name="ck_document_links_distinct"),
        Index("ix_document_links_document", "org_id", "document_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    related_document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ApiKey(Base):
    """A per-organization intake credential; only the SHA-256 of the key is stored."""

    __tablename__ = "api_keys"
    __table_args__ = (Index("ix_api_keys_org", "org_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    key_prefix: Mapped[str] = mapped_column(String(8), nullable=False, unique=True)
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    scopes: Mapped[str] = mapped_column(
        String(200), nullable=False, default="documents:write", server_default="documents:write"
    )
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EmailInbox(Base):
    """The one mailbox an organization receives documents from."""

    __tablename__ = "email_inboxes"
    __table_args__ = (
        CheckConstraint("backend IN ('imap', 'mailpit')", name="ck_email_inboxes_backend"),
    )

    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), primary_key=True)
    backend: Mapped[str] = mapped_column(String(20), nullable=False)
    address: Mapped[str] = mapped_column(String(320), nullable=False)
    config_json: Mapped[str] = mapped_column(Text, nullable=False)
    credentials_encrypted: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=true()
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    last_polled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_poll_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(300))
    last_test_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_test_ok: Mapped[bool | None] = mapped_column(Boolean)
    last_test_message: Mapped[str | None] = mapped_column(String(300))


class EmailMessage(Base):
    """One processed inbound message per inbox; the unique uid makes polling idempotent."""

    __tablename__ = "email_messages"
    __table_args__ = (
        ForeignKeyConstraint(["org_id", "document_id"], ["documents.org_id", "documents.id"]),
        UniqueConstraint("org_id", "uid", name="uq_email_messages_org_uid"),
        Index("ix_email_messages_document", "org_id", "document_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    uid: Mapped[str] = mapped_column(String(255), nullable=False)
    sender: Mapped[str] = mapped_column(String(320), nullable=False)
    subject: Mapped[str] = mapped_column(String(300), nullable=False)
    # The first document created from the message; document_count holds the total.
    document_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    document_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    error: Mapped[str | None] = mapped_column(String(300))
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
