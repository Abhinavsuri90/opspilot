"""Tenant-inclusive foreign key from action_attempts to actions.

Revision ID: 0009
Revises: 0008
"""

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

# Name Postgres generated for the single-column key created inline by 0008.
LEGACY_FK = "action_attempts_action_id_fkey"
TENANT_FK = "fk_action_attempts_org_action"


def upgrade() -> None:
    op.create_unique_constraint("uq_actions_org_id", "actions", ["org_id", "id"])
    op.drop_constraint(LEGACY_FK, "action_attempts", type_="foreignkey")
    op.create_foreign_key(
        TENANT_FK, "action_attempts", "actions", ["org_id", "action_id"], ["org_id", "id"]
    )


def downgrade() -> None:
    op.drop_constraint(TENANT_FK, "action_attempts", type_="foreignkey")
    op.create_foreign_key(LEGACY_FK, "action_attempts", "actions", ["action_id"], ["id"])
    op.drop_constraint("uq_actions_org_id", "actions", type_="unique")
