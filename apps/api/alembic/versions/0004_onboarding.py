"""Organization signup and admin-governed membership lifecycle.

Revision ID: 0004
Revises: 0003
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "organizations",
        sa.Column("default_currency", sa.String(3), server_default="USD", nullable=False),
    )
    op.create_check_constraint(
        "ck_organizations_currency", "organizations", "default_currency ~ '^[A-Z]{3}$'"
    )
    op.add_column(
        "memberships", sa.Column("status", sa.String(20), server_default="active", nullable=False)
    )
    op.add_column("memberships", sa.Column("requested_role", sa.String(30)))
    op.add_column(
        "memberships",
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.add_column("memberships", sa.Column("decided_at", sa.DateTime(timezone=True)))
    op.add_column(
        "memberships",
        sa.Column("decided_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id")),
    )
    op.create_check_constraint(
        "ck_memberships_status",
        "memberships",
        "status IN ('pending', 'active', 'rejected', 'suspended')",
    )
    op.create_check_constraint(
        "ck_memberships_role", "memberships", "role IN ('admin', 'reviewer', 'member', 'viewer')"
    )
    op.create_check_constraint(
        "ck_memberships_requested_role",
        "memberships",
        "requested_role IS NULL OR requested_role IN ('admin', 'reviewer', 'member', 'viewer')",
    )
    op.create_index("ix_memberships_org_status", "memberships", ["org_id", "status"])
    # The HTTP process keeps using opspilot_app. Existing RLS applies to every
    # membership, workflow, and audit write within the chosen tenant transaction.
    op.execute("GRANT INSERT ON organizations, users, workflow_configs TO opspilot_app")
    op.execute("GRANT INSERT, UPDATE ON memberships TO opspilot_app")


def downgrade() -> None:
    op.execute("REVOKE INSERT, UPDATE ON memberships FROM opspilot_app")
    op.execute("REVOKE INSERT ON organizations, users, workflow_configs FROM opspilot_app")
    op.drop_index("ix_memberships_org_status", table_name="memberships")
    for name in ("ck_memberships_requested_role", "ck_memberships_role", "ck_memberships_status"):
        op.drop_constraint(name, "memberships", type_="check")
    for column in ("decided_by", "decided_at", "created_at", "requested_role", "status"):
        op.drop_column("memberships", column)
    op.drop_constraint("ck_organizations_currency", "organizations", type_="check")
    op.drop_column("organizations", "default_currency")
