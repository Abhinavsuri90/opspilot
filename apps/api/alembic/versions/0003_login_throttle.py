"""Durable login throttling shared by all API instances.

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "login_attempts",
        sa.Column("identity_hash", sa.String(64), primary_key=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_login_attempts_window_started", "login_attempts", ["window_started_at"])
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON login_attempts TO opspilot_app")


def downgrade() -> None:
    op.drop_index("ix_login_attempts_window_started", table_name="login_attempts")
    op.drop_table("login_attempts")
