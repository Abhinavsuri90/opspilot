"""Verified money provenance and an RLS-safe rerun of the audit document backfill.

Revision ID: 0007
Revises: 0006
"""

import sqlalchemy as sa

from alembic import op
from app.maintenance import backfill_audit_document_ids, backfill_verified_source

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("invoice_metadata", sa.Column("verified_source", sa.String(10)))
    op.create_check_constraint(
        "ck_invoice_verified_source",
        "invoice_metadata",
        "verified_source IS NULL OR verified_source IN ('reviewer', 'derived')",
    )
    connection = op.get_bind()
    # 0006 ran its backfill under FORCE ROW LEVEL SECURITY without a tenant context,
    # which updates nothing for a non-superuser owner. Rerun it with row security off.
    backfill_audit_document_ids(connection)
    backfill_verified_source(connection)


def downgrade() -> None:
    op.drop_constraint("ck_invoice_verified_source", "invoice_metadata", type_="check")
    op.drop_column("invoice_metadata", "verified_source")
