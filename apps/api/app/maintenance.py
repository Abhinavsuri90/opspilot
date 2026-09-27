"""Owner-run data maintenance shared by migrations and their tests.

Tenant tables use FORCE ROW LEVEL SECURITY, so even the owning role sees no rows
without a tenant context. Maintenance statements disable row security for their
transaction; a role that lacks BYPASSRLS or ownership fails loudly instead of
silently updating nothing.
"""

from sqlalchemy import text
from sqlalchemy.engine import Connection

UUID_PATTERN = "^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
AUDIT_DOCUMENT_BACKFILL = text(
    "UPDATE audit_events SET document_id = (detail_json::jsonb ->> 'document_id')::uuid "
    "WHERE document_id IS NULL "
    "AND detail_json ~ '^\\s*\\{' "
    "AND jsonb_typeof(detail_json::jsonb) = 'object' "
    f"AND (detail_json::jsonb ->> 'document_id') ~* '{UUID_PATTERN}'"
)
VERIFIED_SOURCE_BACKFILL = text(
    "UPDATE invoice_metadata SET verified_source = 'reviewer' "
    "WHERE verified_amount IS NOT NULL AND verified_source IS NULL"
)


def disable_row_security(connection: Connection) -> None:
    """Transaction-scoped; must run inside the caller's transaction."""
    connection.execute(text("SET LOCAL row_security = off"))


def backfill_audit_document_ids(connection: Connection) -> int:
    """Copy document ids recorded only inside detail_json; idempotent."""
    disable_row_security(connection)
    return int(connection.execute(AUDIT_DOCUMENT_BACKFILL).rowcount)


def backfill_verified_source(connection: Connection) -> int:
    """Money verified before Phase 2 was always entered by a reviewer."""
    disable_row_security(connection)
    return int(connection.execute(VERIFIED_SOURCE_BACKFILL).rowcount)
