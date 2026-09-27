"""Intake channels and templates: document sources, near-duplicate links, API keys, email.

Revision ID: 0010
Revises: 0009
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

TENANT_CHECK = "org_id = NULLIF(current_setting('app.current_org', true), '')::uuid"
# A key is looked up by its public prefix before any tenant is known. This policy exposes
# exactly the row whose prefix the caller already presented, and nothing else.
PREFIX_CHECK = "key_prefix = NULLIF(current_setting('app.api_key_prefix', true), '')"


def uuid_column(name: str, nullable: bool = False, primary: bool = False) -> sa.Column[object]:
    return sa.Column(name, postgresql.UUID(as_uuid=True), nullable=nullable, primary_key=primary)


def tenant_column() -> sa.Column[object]:
    return sa.Column(
        "org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False
    )


def timestamp(name: str, nullable: bool = False, default_now: bool = True) -> sa.Column[object]:
    return sa.Column(
        name,
        sa.DateTime(timezone=True),
        server_default=sa.func.now() if default_now else None,
        nullable=nullable,
    )


def enable_rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {table}_org_isolation ON {table} "
        f"USING ({TENANT_CHECK}) WITH CHECK ({TENANT_CHECK})"
    )


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("source", sa.String(20), server_default="upload", nullable=False),
    )
    op.add_column("documents", sa.Column("source_ref", sa.String(300)))
    op.add_column("documents", sa.Column("context_text", sa.Text()))
    op.create_check_constraint(
        "ck_documents_source", "documents", "source IN ('upload', 'email', 'api')"
    )
    op.create_index(
        "ix_documents_org_type_created", "documents", ["org_id", "document_type", "created_at"]
    )

    op.create_table(
        "document_links",
        uuid_column("id", primary=True),
        tenant_column(),
        uuid_column("document_id"),
        uuid_column("related_document_id"),
        sa.Column("kind", sa.String(30), nullable=False),
        timestamp("created_at"),
        sa.ForeignKeyConstraint(["org_id", "document_id"], ["documents.org_id", "documents.id"]),
        sa.ForeignKeyConstraint(
            ["org_id", "related_document_id"], ["documents.org_id", "documents.id"]
        ),
        sa.UniqueConstraint(
            "org_id", "document_id", "related_document_id", "kind", name="uq_document_links_pair"
        ),
        sa.CheckConstraint("kind IN ('near_duplicate')", name="ck_document_links_kind"),
        sa.CheckConstraint("document_id <> related_document_id", name="ck_document_links_distinct"),
    )
    op.create_index("ix_document_links_document", "document_links", ["org_id", "document_id"])

    op.create_table(
        "api_keys",
        uuid_column("id", primary=True),
        tenant_column(),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("key_prefix", sa.String(8), nullable=False, unique=True),
        sa.Column("key_hash", sa.String(64), nullable=False),
        sa.Column("scopes", sa.String(200), server_default="documents:write", nullable=False),
        sa.Column(
            "created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False
        ),
        timestamp("created_at"),
        timestamp("last_used_at", nullable=True, default_now=False),
        timestamp("revoked_at", nullable=True, default_now=False),
    )
    op.create_index("ix_api_keys_org", "api_keys", ["org_id", "created_at"])

    op.create_table(
        "email_inboxes",
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id"),
            primary_key=True,
        ),
        sa.Column("backend", sa.String(20), nullable=False),
        sa.Column("address", sa.String(320), nullable=False),
        sa.Column("config_json", sa.Text(), nullable=False),
        sa.Column("credentials_encrypted", sa.Text()),
        sa.Column("active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False
        ),
        timestamp("created_at"),
        timestamp("updated_at"),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id")),
        timestamp("last_polled_at", nullable=True, default_now=False),
        timestamp("next_poll_at", nullable=True, default_now=False),
        sa.Column("last_error", sa.String(300)),
        timestamp("last_test_at", nullable=True, default_now=False),
        sa.Column("last_test_ok", sa.Boolean()),
        sa.Column("last_test_message", sa.String(300)),
        sa.CheckConstraint("backend IN ('imap', 'mailpit')", name="ck_email_inboxes_backend"),
    )

    op.create_table(
        "email_messages",
        uuid_column("id", primary=True),
        tenant_column(),
        sa.Column("uid", sa.String(255), nullable=False),
        sa.Column("sender", sa.String(320), nullable=False),
        sa.Column("subject", sa.String(300), nullable=False),
        uuid_column("document_id", nullable=True),
        sa.Column("document_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error", sa.String(300)),
        timestamp("processed_at"),
        sa.ForeignKeyConstraint(["org_id", "document_id"], ["documents.org_id", "documents.id"]),
        sa.UniqueConstraint("org_id", "uid", name="uq_email_messages_org_uid"),
    )
    op.create_index("ix_email_messages_document", "email_messages", ["org_id", "document_id"])

    for table in ("document_links", "api_keys", "email_inboxes", "email_messages"):
        enable_rls(table)
    op.execute(
        f"CREATE POLICY api_keys_prefix_lookup ON api_keys FOR SELECT USING ({PREFIX_CHECK})"
    )
    op.execute("GRANT SELECT, INSERT ON document_links, email_messages TO opspilot_app")
    op.execute("GRANT SELECT, INSERT, UPDATE ON api_keys, email_inboxes TO opspilot_app")


def downgrade() -> None:
    op.execute("REVOKE SELECT, INSERT, UPDATE ON api_keys, email_inboxes FROM opspilot_app")
    op.execute("REVOKE SELECT, INSERT ON document_links, email_messages FROM opspilot_app")
    op.drop_index("ix_email_messages_document", table_name="email_messages")
    op.drop_table("email_messages")
    op.drop_table("email_inboxes")
    op.drop_index("ix_api_keys_org", table_name="api_keys")
    op.drop_table("api_keys")
    op.drop_index("ix_document_links_document", table_name="document_links")
    op.drop_table("document_links")
    op.drop_index("ix_documents_org_type_created", table_name="documents")
    op.drop_constraint("ck_documents_source", "documents", type_="check")
    op.drop_column("documents", "context_text")
    op.drop_column("documents", "source_ref")
    op.drop_column("documents", "source")
