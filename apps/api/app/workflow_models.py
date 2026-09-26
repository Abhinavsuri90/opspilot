"""Invoice collaboration records, separate from immutable extraction evidence."""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base


class InvoiceCategory(Base):
    __tablename__ = "invoice_categories"
    __table_args__ = (
        UniqueConstraint("org_id", "id", name="uq_categories_org_id"),
        UniqueConstraint("org_id", "name_key", name="uq_categories_org_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    name_key: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    version: Mapped[int] = mapped_column(nullable=False, default=1)


class InvoiceMetadata(Base):
    __tablename__ = "invoice_metadata"
    __table_args__ = (
        ForeignKeyConstraint(["org_id", "document_id"], ["documents.org_id", "documents.id"]),
        ForeignKeyConstraint(
            ["org_id", "category_id"], ["invoice_categories.org_id", "invoice_categories.id"]
        ),
        ForeignKeyConstraint(
            ["org_id", "assigned_reviewer_id"], ["memberships.org_id", "memberships.user_id"]
        ),
        CheckConstraint("visibility IN ('workspace', 'restricted')", name="ck_invoice_visibility"),
        CheckConstraint("version >= 0", name="ck_invoice_version"),
        CheckConstraint(
            "(verified_amount IS NULL AND currency IS NULL) OR "
            "(verified_amount IS NOT NULL AND verified_amount >= 0 AND currency IS NOT NULL)",
            name="ck_invoice_verified_money",
        ),
        Index("ix_invoice_metadata_category", "org_id", "category_id"),
    )

    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    category_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    assigned_reviewer_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    verified_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    currency: Mapped[str | None] = mapped_column(String(3))
    visibility: Mapped[str] = mapped_column(String(20), default="workspace", nullable=False)
    version: Mapped[int] = mapped_column(default=0, nullable=False)


class InvoiceComment(Base):
    __tablename__ = "invoice_comments"
    __table_args__ = (
        ForeignKeyConstraint(["org_id", "document_id"], ["documents.org_id", "documents.id"]),
        ForeignKeyConstraint(
            ["org_id", "author_user_id"], ["memberships.org_id", "memberships.user_id"]
        ),
        Index("ix_invoice_comments_document", "org_id", "document_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    author_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class InvoiceGrant(Base):
    __tablename__ = "invoice_grants"
    __table_args__ = (
        ForeignKeyConstraint(["org_id", "document_id"], ["documents.org_id", "documents.id"]),
        ForeignKeyConstraint(["org_id", "user_id"], ["memberships.org_id", "memberships.user_id"]),
        Index("ix_invoice_grants_user", "org_id", "user_id"),
    )

    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False)


class InvoiceReview(Base):
    __tablename__ = "invoice_reviews"
    __table_args__ = (
        ForeignKeyConstraint(["org_id", "document_id"], ["documents.org_id", "documents.id"]),
        ForeignKeyConstraint(
            ["org_id", "actor_user_id"], ["memberships.org_id", "memberships.user_id"]
        ),
        CheckConstraint("decision IN ('approve', 'reject', 'reopen')", name="ck_invoice_decision"),
        Index("ix_invoice_reviews_document", "org_id", "document_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    actor_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    decision: Mapped[str] = mapped_column(String(20), nullable=False)
    comment: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
