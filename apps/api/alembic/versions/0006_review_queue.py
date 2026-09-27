"""Confidence columns, field corrections, review tasks and document audit links.

Revision ID: 0006
Revises: 0005
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

TENANT_CHECK = "org_id = NULLIF(current_setting('app.current_org', true), '')::uuid"


def uuid_column(name: str, nullable: bool = False, primary: bool = False) -> sa.Column[object]:
    return sa.Column(name, postgresql.UUID(as_uuid=True), nullable=nullable, primary_key=primary)


def tenant_column() -> sa.Column[object]:
    return sa.Column(
        "org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False
    )


def document_fk() -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(["org_id", "document_id"], ["documents.org_id", "documents.id"])


def enable_rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {table}_org_isolation ON {table} "
        f"USING ({TENANT_CHECK}) WITH CHECK ({TENANT_CHECK})"
    )


def upgrade() -> None:
    # Extraction evidence stays immutable; the new columns describe how confident the
    # pipeline was and why. Existing rows default to auto so old documents are unchanged.
    op.add_column(
        "extracted_fields",
        sa.Column("field_type", sa.String(20), server_default="text", nullable=False),
    )
    op.add_column(
        "extracted_fields",
        sa.Column("required", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column(
        "extracted_fields",
        sa.Column("confidence", sa.Numeric(5, 4), server_default="1.0", nullable=False),
    )
    op.add_column(
        "extracted_fields",
        sa.Column("threshold", sa.Numeric(5, 4), server_default="0.8", nullable=False),
    )
    op.add_column(
        "extracted_fields",
        sa.Column("status", sa.String(20), server_default="auto", nullable=False),
    )
    op.create_check_constraint(
        "ck_extracted_fields_status", "extracted_fields", "status IN ('auto', 'needs_review')"
    )
    op.add_column(
        "extracted_fields",
        sa.Column("signals_json", sa.Text(), server_default="{}", nullable=False),
    )
    op.add_column(
        "extracted_fields",
        sa.Column("reasons_json", sa.Text(), server_default="[]", nullable=False),
    )

    op.create_table(
        "field_corrections",
        uuid_column("id", primary=True),
        tenant_column(),
        uuid_column("document_id"),
        sa.Column(
            "field_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("extracted_fields.id"),
            nullable=False,
        ),
        sa.Column("field_name", sa.String(100), nullable=False),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("before_value", sa.Text(), nullable=False),
        sa.Column("after_value", sa.Text(), nullable=False),
        uuid_column("reviewer_user_id"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        document_fk(),
        sa.ForeignKeyConstraint(
            ["org_id", "reviewer_user_id"], ["memberships.org_id", "memberships.user_id"]
        ),
        sa.CheckConstraint("kind IN ('accept', 'edit')", name="ck_field_corrections_kind"),
    )
    op.create_index(
        "ix_field_corrections_document",
        "field_corrections",
        ["org_id", "document_id", "created_at"],
    )

    op.create_table(
        "review_tasks",
        uuid_column("document_id", primary=True),
        tenant_column(),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sla_minutes", sa.Integer(), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("outcome", sa.String(20)),
        sa.Column("version", sa.Integer(), server_default="0", nullable=False),
        document_fk(),
        sa.CheckConstraint(
            "outcome IS NULL OR outcome IN ('approved', 'rejected')", name="ck_review_tasks_outcome"
        ),
    )
    op.create_index("ix_review_tasks_due", "review_tasks", ["org_id", "due_at"])

    op.add_column(
        "documents",
        sa.Column("document_type", sa.String(50), server_default="invoice", nullable=False),
    )
    op.add_column("documents", sa.Column("trace_id", sa.String(64)))

    op.add_column("audit_events", sa.Column("document_id", postgresql.UUID(as_uuid=True)))
    op.create_index(
        "ix_audit_events_document", "audit_events", ["org_id", "document_id", "created_at"]
    )
    # Earlier releases recorded the document only inside detail_json.
    op.execute(
        "UPDATE audit_events SET document_id = (detail_json::jsonb ->> 'document_id')::uuid "
        "WHERE document_id IS NULL "
        "AND detail_json ~ '^\\s*\\{' "
        "AND jsonb_typeof(detail_json::jsonb) = 'object' "
        "AND (detail_json::jsonb ->> 'document_id') ~* "
        "'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'"
    )

    op.create_index(
        "ix_extraction_runs_document", "extraction_runs", ["org_id", "document_id", "created_at"]
    )
    op.create_index("ix_documents_org_created", "documents", ["org_id", "created_at", "id"])
    op.create_index("ix_outbox_document", "outbox_events", ["org_id", "document_id"])

    for table in ("field_corrections", "review_tasks"):
        enable_rls(table)
    # Corrections are append only; review tasks are refreshed on reopen.
    op.execute("GRANT SELECT, INSERT ON field_corrections TO opspilot_app")
    op.execute("GRANT SELECT, INSERT, UPDATE ON review_tasks TO opspilot_app")
    # Already granted by 0004; re-asserted because GRANT is idempotent and the
    # upcoming config editor (append-only version rows) depends on it.
    op.execute("GRANT INSERT ON workflow_configs TO opspilot_app")


def downgrade() -> None:
    op.execute("REVOKE SELECT, INSERT, UPDATE ON review_tasks FROM opspilot_app")
    op.execute("REVOKE SELECT, INSERT ON field_corrections FROM opspilot_app")
    op.drop_index("ix_outbox_document", table_name="outbox_events")
    op.drop_index("ix_documents_org_created", table_name="documents")
    op.drop_index("ix_extraction_runs_document", table_name="extraction_runs")
    op.drop_index("ix_audit_events_document", table_name="audit_events")
    op.drop_column("audit_events", "document_id")
    op.drop_column("documents", "trace_id")
    op.drop_column("documents", "document_type")
    op.drop_index("ix_review_tasks_due", table_name="review_tasks")
    op.drop_table("review_tasks")
    op.drop_index("ix_field_corrections_document", table_name="field_corrections")
    op.drop_table("field_corrections")
    op.drop_constraint("ck_extracted_fields_status", "extracted_fields", type_="check")
    for column in (
        "reasons_json",
        "signals_json",
        "status",
        "threshold",
        "confidence",
        "required",
        "field_type",
    ):
        op.drop_column("extracted_fields", column)
