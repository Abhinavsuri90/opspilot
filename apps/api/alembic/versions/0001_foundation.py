"""Foundation tables, app role, tenant RLS and append-only audit grants.

Revision ID: 0001
Revises:
"""

import os

import sqlalchemy as sa
from psycopg import sql
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("slug", sa.String(80), nullable=False, unique=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False, unique=True),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_table(
        "memberships",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id"),
            nullable=False,
        ),
        sa.Column(
            "user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("role", sa.String(30), nullable=False),
        sa.UniqueConstraint("org_id", "user_id", name="uq_membership_org_user"),
    )
    op.create_index("ix_memberships_org_role", "memberships", ["org_id", "role"])
    op.create_table(
        "workflow_configs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("config_json", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("org_id", "version", name="uq_workflow_org_version"),
    )
    op.create_table(
        "audit_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id"),
            nullable=False,
        ),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("detail_json", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_audit_events_org_created", "audit_events", ["org_id", "created_at"])

    connection = op.get_bind()
    connection.execute(
        sa.text(
            "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles "
            "WHERE rolname = 'opspilot_app') THEN CREATE ROLE opspilot_app LOGIN; "
            "END IF; END $$"
        )
    )
    password = os.environ["APP_DB_PASSWORD"]
    raw_connection = connection.connection.driver_connection
    with raw_connection.cursor() as cursor:
        cursor.execute(sql.SQL("ALTER ROLE opspilot_app PASSWORD {}").format(sql.Literal(password)))
    database_name = connection.scalar(sa.text("SELECT current_database()"))
    with raw_connection.cursor() as cursor:
        cursor.execute(
            sql.SQL("GRANT CONNECT ON DATABASE {} TO opspilot_app").format(
                sql.Identifier(database_name)
            )
        )
    connection.execute(sa.text("GRANT USAGE ON SCHEMA public TO opspilot_app"))
    connection.execute(sa.text("GRANT SELECT ON organizations, users TO opspilot_app"))
    connection.execute(sa.text("GRANT SELECT ON memberships, workflow_configs TO opspilot_app"))
    connection.execute(sa.text("GRANT SELECT, INSERT ON audit_events TO opspilot_app"))

    for table in ("memberships", "workflow_configs", "audit_events"):
        connection.execute(sa.text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"))
        connection.execute(sa.text(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY"))
        tenant_check = "org_id = NULLIF(current_setting('app.current_org', true), '')::uuid"
        connection.execute(
            sa.text(
                f"CREATE POLICY {table}_org_isolation ON {table} "
                f"USING ({tenant_check}) WITH CHECK ({tenant_check})"
            )
        )


def downgrade() -> None:
    for table in ("audit_events", "workflow_configs", "memberships"):
        op.execute(f"DROP POLICY IF EXISTS {table}_org_isolation ON {table}")
    op.drop_index("ix_audit_events_org_created", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_table("workflow_configs")
    op.drop_index("ix_memberships_org_role", table_name="memberships")
    op.drop_table("memberships")
    op.drop_table("users")
    op.drop_table("organizations")
