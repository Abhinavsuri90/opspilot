"""Governance records: org switches, action policies, connectors, actions and attempts."""

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
    false,
    func,
    true,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base

ACTION_STATUSES = (
    "proposed",
    "approved",
    "rejected",
    "executing",
    "succeeded",
    "failed",
    "retrying",
    "dead_lettered",
    "shadowed",
    "forbidden",
)
# Statuses that still need a worker or a human; a document with one of these is actions_pending.
OPEN_ACTION_STATUSES = frozenset({"proposed", "approved", "executing", "retrying", "dead_lettered"})
POLICY_MODES = ("auto", "needs_approval", "forbidden")
CONNECTOR_TYPES = ("webhook", "csv_export", "postgres_table", "google_sheets")


class OrgSettings(Base):
    """Per-organization agent switches; created lazily on first read."""

    __tablename__ = "org_settings"

    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), primary_key=True)
    kill_switch: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    shadow_mode: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))


class OrgActionPolicy(Base):
    """Per-organization override of the workflow config's default action policy."""

    __tablename__ = "action_policies"
    __table_args__ = (
        CheckConstraint(
            "mode IN ('auto', 'needs_approval', 'forbidden')", name="ck_action_policies_mode"
        ),
    )

    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), primary_key=True)
    action_type: Mapped[str] = mapped_column(String(50), primary_key=True)
    mode: Mapped[str] = mapped_column(String(20), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))


class ConnectorInstance(Base):
    """A configured destination system; credentials are Fernet encrypted at rest."""

    __tablename__ = "connector_instances"
    __table_args__ = (
        UniqueConstraint("org_id", "id", name="uq_connector_instances_org_id"),
        UniqueConstraint("org_id", "name", name="uq_connector_instances_org_name"),
        CheckConstraint(
            "connector_type IN ('webhook', 'csv_export', 'postgres_table', 'google_sheets')",
            name="ck_connector_instances_type",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    connector_type: Mapped[str] = mapped_column(String(30), nullable=False)
    config_json: Mapped[str] = mapped_column(Text, nullable=False)
    credentials_encrypted: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=true()
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_test_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_test_ok: Mapped[bool | None] = mapped_column(Boolean)
    last_test_message: Mapped[str | None] = mapped_column(String(300))


class Action(Base):
    """One proposed external side effect for one document and destination."""

    __tablename__ = "actions"
    __table_args__ = (
        ForeignKeyConstraint(["org_id", "document_id"], ["documents.org_id", "documents.id"]),
        ForeignKeyConstraint(
            ["org_id", "connector_id"], ["connector_instances.org_id", "connector_instances.id"]
        ),
        UniqueConstraint("org_id", "idempotency_key", name="uq_actions_org_idempotency"),
        UniqueConstraint("org_id", "id", name="uq_actions_org_id"),
        CheckConstraint(
            "status IN (" + ", ".join(f"'{status}'" for status in ACTION_STATUSES) + ")",
            name="ck_actions_status",
        ),
        CheckConstraint(
            "policy_mode IN ('auto', 'needs_approval', 'forbidden')", name="ck_actions_policy"
        ),
        Index("ix_actions_org_status_next", "org_id", "status", "next_attempt_at"),
        Index("ix_actions_org_document", "org_id", "document_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    connector_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    action_type: Mapped[str] = mapped_column(String(50), nullable=False)
    destination: Mapped[str] = mapped_column(String(100), nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    preview_json: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    policy_mode: Mapped[str] = mapped_column(String(20), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(80), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result_json: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(String(500))
    proposed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    decided_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_comment: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=""
    )
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")


class ActionAttempt(Base):
    """Append-only record of one connector execution attempt."""

    __tablename__ = "action_attempts"
    __table_args__ = (
        # Tenant-inclusive foreign key: an attempt can never point at another tenant's action.
        ForeignKeyConstraint(["org_id", "action_id"], ["actions.org_id", "actions.id"]),
        Index("ix_action_attempts_org_action", "org_id", "action_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    action_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    ok: Mapped[bool] = mapped_column(Boolean, nullable=False)
    response_summary: Mapped[str | None] = mapped_column(String(500))
    error: Mapped[str | None] = mapped_column(String(500))
