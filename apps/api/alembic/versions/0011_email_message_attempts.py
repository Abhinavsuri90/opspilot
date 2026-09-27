"""Email message retry budget and composite message keys.

Revision ID: 0011
Revises: 0010
"""

import sqlalchemy as sa

from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "email_messages",
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
    )
    # IMAP keys are <folder>:<uidvalidity>:<uid>; folder names alone may be 200 characters.
    op.alter_column(
        "email_messages",
        "uid",
        existing_type=sa.String(255),
        type_=sa.String(400),
        existing_nullable=False,
    )
    # The poller counts failed attempts on the row, which needs UPDATE next to INSERT.
    op.execute("GRANT UPDATE ON email_messages TO opspilot_app")


def downgrade() -> None:
    op.execute("REVOKE UPDATE ON email_messages FROM opspilot_app")
    op.alter_column(
        "email_messages",
        "uid",
        existing_type=sa.String(400),
        type_=sa.String(255),
        existing_nullable=False,
    )
    op.drop_column("email_messages", "attempts")
