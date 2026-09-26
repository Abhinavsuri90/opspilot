"""Tenant-isolated categories, invoice collaboration and review decisions.

Revision ID: 0005
Revises: 0004
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def uuid_column(name: str, nullable: bool = False, primary: bool = False) -> sa.Column[object]:
    return sa.Column(name, postgresql.UUID(as_uuid=True), nullable=nullable, primary_key=primary)


def tenant_column() -> sa.Column[object]:
    return sa.Column(
        "org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False
    )


def created_at() -> sa.Column[object]:
    return sa.Column(
        "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )


def document_fk() -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(["org_id", "document_id"], ["documents.org_id", "documents.id"])


def membership_fk(column: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["org_id", column], ["memberships.org_id", "memberships.user_id"]
    )


def upgrade() -> None:
    op.create_unique_constraint("uq_documents_org_id", "documents", ["org_id", "id"])
    op.create_table(
        "invoice_categories",
        uuid_column("id", primary=True),
        tenant_column(),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("name_key", sa.String(160), nullable=False),
        sa.Column("description", sa.String(500), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.UniqueConstraint("org_id", "id", name="uq_categories_org_id"),
        sa.UniqueConstraint("org_id", "name_key", name="uq_categories_org_name"),
    )
    op.create_table(
        "invoice_metadata",
        uuid_column("document_id", primary=True),
        tenant_column(),
        uuid_column("category_id", nullable=True),
        uuid_column("assigned_reviewer_id", nullable=True),
        sa.Column("verified_amount", sa.Numeric(20, 4)),
        sa.Column("currency", sa.String(3)),
        sa.Column("visibility", sa.String(20), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        document_fk(),
        sa.ForeignKeyConstraint(
            ["org_id", "category_id"], ["invoice_categories.org_id", "invoice_categories.id"]
        ),
        membership_fk("assigned_reviewer_id"),
        sa.CheckConstraint(
            "visibility IN ('workspace', 'restricted')", name="ck_invoice_visibility"
        ),
        sa.CheckConstraint("version >= 0", name="ck_invoice_version"),
        sa.CheckConstraint(
            "(verified_amount IS NULL AND currency IS NULL) OR "
            "(verified_amount IS NOT NULL AND verified_amount >= 0 AND currency IS NOT NULL)",
            name="ck_invoice_verified_money",
        ),
    )
    op.create_index("ix_invoice_metadata_category", "invoice_metadata", ["org_id", "category_id"])
    op.create_table(
        "invoice_comments",
        uuid_column("id", primary=True),
        tenant_column(),
        uuid_column("document_id"),
        uuid_column("author_user_id"),
        sa.Column("body", sa.Text(), nullable=False),
        created_at(),
        document_fk(),
        membership_fk("author_user_id"),
    )
    op.create_index(
        "ix_invoice_comments_document", "invoice_comments", ["org_id", "document_id", "created_at"]
    )
    op.create_table(
        "invoice_grants",
        uuid_column("document_id", primary=True),
        uuid_column("user_id", primary=True),
        tenant_column(),
        document_fk(),
        membership_fk("user_id"),
    )
    op.create_index("ix_invoice_grants_user", "invoice_grants", ["org_id", "user_id"])
    op.create_table(
        "invoice_reviews",
        uuid_column("id", primary=True),
        tenant_column(),
        uuid_column("document_id"),
        uuid_column("actor_user_id"),
        sa.Column("decision", sa.String(20), nullable=False),
        sa.Column("comment", sa.Text(), nullable=False),
        created_at(),
        document_fk(),
        membership_fk("actor_user_id"),
        sa.CheckConstraint(
            "decision IN ('approve', 'reject', 'reopen')", name="ck_invoice_decision"
        ),
    )
    op.create_index(
        "ix_invoice_reviews_document", "invoice_reviews", ["org_id", "document_id", "created_at"]
    )

    for table in (
        "invoice_categories",
        "invoice_metadata",
        "invoice_comments",
        "invoice_grants",
        "invoice_reviews",
    ):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        check = "org_id = NULLIF(current_setting('app.current_org', true), '')::uuid"
        op.execute(
            f"CREATE POLICY {table}_org_isolation ON {table} USING ({check}) WITH CHECK ({check})"
        )
    op.execute(
        "GRANT SELECT, INSERT, UPDATE ON invoice_categories, invoice_metadata TO opspilot_app"
    )
    op.execute("GRANT SELECT, INSERT, DELETE ON invoice_grants TO opspilot_app")
    # Discussion and decision history is append only for the application role.
    op.execute("GRANT SELECT, INSERT ON invoice_comments, invoice_reviews TO opspilot_app")


def downgrade() -> None:
    for table in (
        "invoice_reviews",
        "invoice_grants",
        "invoice_comments",
        "invoice_metadata",
        "invoice_categories",
    ):
        op.drop_table(table)
    op.drop_constraint("uq_documents_org_id", "documents", type_="unique")
