"""Governed actions: org settings, action policies, connectors, actions and attempts.

Revision ID: 0008
Revises: 0007
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

TENANT_CHECK = "org_id = NULLIF(current_setting('app.current_org', true), '')::uuid"
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
    op.create_table(
        "org_settings",
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id"),
            primary_key=True,
        ),
        sa.Column("kill_switch", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("shadow_mode", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="0", nullable=False),
        timestamp("updated_at"),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id")),
    )
    op.create_table(
        "action_policies",
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id"),
            primary_key=True,
        ),
        sa.Column("action_type", sa.String(50), primary_key=True),
        sa.Column("mode", sa.String(20), nullable=False),
        sa.Column("version", sa.Integer(), server_default="0", nullable=False),
        timestamp("updated_at"),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.CheckConstraint(
            "mode IN ('auto', 'needs_approval', 'forbidden')", name="ck_action_policies_mode"
        ),
    )
    op.create_table(
        "connector_instances",
        uuid_column("id", primary=True),
        tenant_column(),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("connector_type", sa.String(30), nullable=False),
        sa.Column("config_json", sa.Text(), nullable=False),
        sa.Column("credentials_encrypted", sa.Text()),
        sa.Column("active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="0", nullable=False),
        timestamp("created_at"),
        timestamp("updated_at"),
        timestamp("last_test_at", nullable=True, default_now=False),
        sa.Column("last_test_ok", sa.Boolean()),
        sa.Column("last_test_message", sa.String(300)),
        sa.UniqueConstraint("org_id", "id", name="uq_connector_instances_org_id"),
        sa.UniqueConstraint("org_id", "name", name="uq_connector_instances_org_name"),
        sa.CheckConstraint(
            "connector_type IN ('webhook', 'csv_export', 'postgres_table', 'google_sheets')",
            name="ck_connector_instances_type",
        ),
    )
    op.create_table(
        "actions",
        uuid_column("id", primary=True),
        tenant_column(),
        uuid_column("document_id"),
        uuid_column("connector_id", nullable=True),
        sa.Column("action_type", sa.String(50), nullable=False),
        sa.Column("destination", sa.String(100), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("preview_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("policy_mode", sa.String(20), nullable=False),
        sa.Column("idempotency_key", sa.String(80), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        timestamp("next_attempt_at", nullable=True, default_now=False),
        timestamp("claimed_at", nullable=True, default_now=False),
        sa.Column("result_json", sa.Text()),
        sa.Column("error", sa.String(500)),
        timestamp("proposed_at"),
        sa.Column("decided_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id")),
        timestamp("decided_at", nullable=True, default_now=False),
        sa.Column("decision_comment", sa.Text(), server_default="", nullable=False),
        timestamp("executed_at", nullable=True, default_now=False),
        sa.Column("version", sa.Integer(), server_default="0", nullable=False),
        sa.ForeignKeyConstraint(["org_id", "document_id"], ["documents.org_id", "documents.id"]),
        sa.ForeignKeyConstraint(
            ["org_id", "connector_id"], ["connector_instances.org_id", "connector_instances.id"]
        ),
        sa.UniqueConstraint("org_id", "idempotency_key", name="uq_actions_org_idempotency"),
        sa.CheckConstraint(
            "status IN (" + ", ".join(f"'{status}'" for status in ACTION_STATUSES) + ")",
            name="ck_actions_status",
        ),
        sa.CheckConstraint(
            "policy_mode IN ('auto', 'needs_approval', 'forbidden')", name="ck_actions_policy"
        ),
    )
    op.create_index(
        "ix_actions_org_status_next", "actions", ["org_id", "status", "next_attempt_at"]
    )
    op.create_index("ix_actions_org_document", "actions", ["org_id", "document_id"])
    op.create_table(
        "action_attempts",
        uuid_column("id", primary=True),
        tenant_column(),
        sa.Column(
            "action_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("actions.id"), nullable=False
        ),
        sa.Column("attempt", sa.Integer(), nullable=False),
        timestamp("started_at"),
        timestamp("finished_at"),
        sa.Column("ok", sa.Boolean(), nullable=False),
        sa.Column("response_summary", sa.String(500)),
        sa.Column("error", sa.String(500)),
    )
    op.create_index("ix_action_attempts_org_action", "action_attempts", ["org_id", "action_id"])

    op.add_column("outbox_events", sa.Column("action_id", postgresql.UUID(as_uuid=True)))
    op.create_index(
        "ix_outbox_org_topic_available",
        "outbox_events",
        ["org_id", "topic", "published_at", "available_at"],
    )

    for table in (
        "org_settings",
        "action_policies",
        "connector_instances",
        "actions",
        "action_attempts",
    ):
        enable_rls(table)
    # Connectors are deactivated rather than deleted; attempts are append only.
    op.execute(
        "GRANT SELECT, INSERT, UPDATE ON org_settings, action_policies, connector_instances, "
        "actions TO opspilot_app"
    )
    op.execute("GRANT SELECT, INSERT ON action_attempts TO opspilot_app")


def downgrade() -> None:
    op.execute("REVOKE SELECT, INSERT ON action_attempts FROM opspilot_app")
    op.execute(
        "REVOKE SELECT, INSERT, UPDATE ON org_settings, action_policies, connector_instances, "
        "actions FROM opspilot_app"
    )
    op.drop_index("ix_outbox_org_topic_available", table_name="outbox_events")
    op.drop_column("outbox_events", "action_id")
    op.drop_index("ix_action_attempts_org_action", table_name="action_attempts")
    op.drop_table("action_attempts")
    op.drop_index("ix_actions_org_document", table_name="actions")
    op.drop_index("ix_actions_org_status_next", table_name="actions")
    op.drop_table("actions")
    op.drop_table("connector_instances")
    op.drop_table("action_policies")
    op.drop_table("org_settings")
