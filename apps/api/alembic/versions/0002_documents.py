"""Tenant-isolated documents, extracted fields, and durable extraction outbox.

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def tenant_column() -> sa.Column[object]:
    return sa.Column(
        "org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False
    )


def id_column() -> sa.Column[object]:
    return sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True)


def upgrade() -> None:
    op.create_table(
        "documents",
        id_column(),
        tenant_column(),
        sa.Column(
            "uploaded_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("content_type", sa.String(100), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("storage_key", sa.String(300), nullable=False),
        sa.Column("workflow_config_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("failure_reason", sa.String(200)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("org_id", "content_hash", name="uq_documents_org_hash"),
    )
    op.create_index(
        "ix_documents_org_status_created", "documents", ["org_id", "status", "created_at"]
    )
    op.create_table(
        "extraction_runs",
        id_column(),
        tenant_column(),
        sa.Column(
            "document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documents.id"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("prompt_version", sa.String(50), nullable=False),
        sa.Column("raw_json", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_table(
        "extracted_fields",
        id_column(),
        tenant_column(),
        sa.Column(
            "document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documents.id"),
            nullable=False,
        ),
        sa.Column(
            "extraction_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("extraction_runs.id"),
            nullable=False,
        ),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("evidence", sa.Text(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
    )
    op.create_index("ix_extracted_fields_document", "extracted_fields", ["org_id", "document_id"])
    op.create_table(
        "outbox_events",
        id_column(),
        tenant_column(),
        sa.Column(
            "document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documents.id"),
            nullable=False,
        ),
        sa.Column("topic", sa.String(100), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column(
            "available_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("claimed_at", sa.DateTime(timezone=True)),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index(
        "ix_outbox_org_available", "outbox_events", ["org_id", "published_at", "available_at"]
    )

    for table in ("documents", "extraction_runs", "extracted_fields", "outbox_events"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        check = "org_id = NULLIF(current_setting('app.current_org', true), '')::uuid"
        op.execute(
            f"CREATE POLICY {table}_org_isolation ON {table} USING ({check}) WITH CHECK ({check})"
        )

    op.execute("GRANT SELECT, INSERT, UPDATE ON documents, outbox_events TO opspilot_app")
    op.execute("GRANT SELECT, INSERT ON extraction_runs, extracted_fields TO opspilot_app")


def downgrade() -> None:
    for table in ("outbox_events", "extracted_fields", "extraction_runs", "documents"):
        op.execute(f"DROP POLICY IF EXISTS {table}_org_isolation ON {table}")
    op.drop_index("ix_outbox_org_available", table_name="outbox_events")
    op.drop_table("outbox_events")
    op.drop_index("ix_extracted_fields_document", table_name="extracted_fields")
    op.drop_table("extracted_fields")
    op.drop_table("extraction_runs")
    op.drop_index("ix_documents_org_status_created", table_name="documents")
    op.drop_table("documents")
