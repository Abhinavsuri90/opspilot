"""Learning loop, model router and cost: llm_calls, memory_items, spend cap, run tiers.

Revision ID: 0012
Revises: 0011
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from app.learning_models import Vector

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None

TENANT_CHECK = "org_id = NULLIF(current_setting('app.current_org', true), '')::uuid"


def uuid_column(name: str, nullable: bool = False, primary: bool = False) -> sa.Column[object]:
    return sa.Column(name, postgresql.UUID(as_uuid=True), nullable=nullable, primary_key=primary)


def tenant_column() -> sa.Column[object]:
    return sa.Column(
        "org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False
    )


def enable_rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {table}_org_isolation ON {table} "
        f"USING ({TENANT_CHECK}) WITH CHECK ({TENANT_CHECK})"
    )


def upgrade() -> None:
    # pgvector ships with the pgvector/pgvector:pg16 image used locally, in CI and on the
    # Oracle host; creating the extension needs the owner role to be a superuser (it is the
    # bootstrap role in every compose file) or the extension to be pre-installed.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "llm_calls",
        uuid_column("id", primary=True),
        tenant_column(),
        uuid_column("document_id", nullable=True),
        sa.Column("purpose", sa.String(20), nullable=False),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("prompt_version", sa.String(50), nullable=False),
        sa.Column("tokens_in", sa.Integer()),
        sa.Column("tokens_out", sa.Integer()),
        sa.Column("cost_cents", sa.Numeric(12, 4)),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("ok", sa.Boolean(), nullable=False),
        sa.Column("error", sa.String(300)),
        sa.Column("trace_id", sa.String(64)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["org_id", "document_id"], ["documents.org_id", "documents.id"]),
        sa.CheckConstraint(
            "purpose IN ('extraction', 'escalation', 'embedding', 'agent')",
            name="ck_llm_calls_purpose",
        ),
    )
    op.create_index("ix_llm_calls_org_created", "llm_calls", ["org_id", "created_at"])
    op.create_index("ix_llm_calls_org_document", "llm_calls", ["org_id", "document_id"])

    op.create_table(
        "memory_items",
        uuid_column("id", primary=True),
        tenant_column(),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("key", sa.String(200), nullable=False),
        sa.Column("content_json", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(256), nullable=True),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("kind IN ('vendor_profile', 'few_shot')", name="ck_memory_items_kind"),
    )
    op.create_index("ix_memory_items_org_kind_key", "memory_items", ["org_id", "kind", "key"])
    op.create_index(
        "uq_memory_items_vendor_profile",
        "memory_items",
        ["org_id", "key"],
        unique=True,
        postgresql_where=sa.text("kind = 'vendor_profile'"),
    )

    op.add_column("org_settings", sa.Column("daily_llm_spend_cap_cents", sa.Integer()))
    op.add_column("extraction_runs", sa.Column("tier1_model", sa.String(100)))
    op.add_column("extraction_runs", sa.Column("tier2_model", sa.String(100)))
    op.add_column(
        "extraction_runs",
        sa.Column("escalated", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column("extraction_runs", sa.Column("cost_cents", sa.Numeric(12, 4)))

    for table in ("llm_calls", "memory_items"):
        enable_rls(table)
    # The ledger is append-only; memory rows are upserted in place (profiles and the bounded
    # few-shot set), so the app role may update but never delete them.
    op.execute("GRANT SELECT, INSERT ON llm_calls TO opspilot_app")
    op.execute("GRANT SELECT, INSERT, UPDATE ON memory_items TO opspilot_app")


def downgrade() -> None:
    op.execute("REVOKE SELECT, INSERT, UPDATE ON memory_items FROM opspilot_app")
    op.execute("REVOKE SELECT, INSERT ON llm_calls FROM opspilot_app")
    op.drop_column("extraction_runs", "cost_cents")
    op.drop_column("extraction_runs", "escalated")
    op.drop_column("extraction_runs", "tier2_model")
    op.drop_column("extraction_runs", "tier1_model")
    op.drop_column("org_settings", "daily_llm_spend_cap_cents")
    op.drop_index("uq_memory_items_vendor_profile", table_name="memory_items")
    op.drop_index("ix_memory_items_org_kind_key", table_name="memory_items")
    op.drop_table("memory_items")
    op.drop_index("ix_llm_calls_org_document", table_name="llm_calls")
    op.drop_index("ix_llm_calls_org_created", table_name="llm_calls")
    op.drop_table("llm_calls")
