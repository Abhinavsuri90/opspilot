"""Owner-run backfills must populate rows even under FORCE ROW LEVEL SECURITY."""

import json
import uuid
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.maintenance import backfill_audit_document_ids, backfill_verified_source
from app.models import AuditEvent, Document, Organization
from app.workflow_models import InvoiceMetadata
from tests.conftest import TenantFactory, owner_engine, postgres


@postgres
def test_audit_document_backfill_fills_legacy_rows_and_is_idempotent() -> None:
    engine = owner_engine()
    document_id = uuid.uuid4()
    legacy_id, invalid_id, unrelated_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    try:
        with Session(engine) as session, session.begin():
            org_id = session.scalar(select(Organization.id).where(Organization.slug == "northwind"))
            assert org_id is not None
            session.add_all(
                [
                    AuditEvent(
                        id=legacy_id,
                        org_id=org_id,
                        event_type="test.legacy",
                        detail_json=json.dumps({"document_id": str(document_id)}),
                    ),
                    AuditEvent(
                        id=invalid_id,
                        org_id=org_id,
                        event_type="test.legacy",
                        detail_json=json.dumps({"document_id": "not-a-uuid"}),
                    ),
                    AuditEvent(
                        id=unrelated_id,
                        org_id=org_id,
                        event_type="test.legacy",
                        detail_json=json.dumps({"slug": "northwind"}),
                    ),
                ]
            )
        with engine.begin() as connection:
            assert backfill_audit_document_ids(connection) >= 1
        with Session(engine) as session:
            filled = session.get(AuditEvent, legacy_id)
            assert filled is not None and filled.document_id == document_id
            for untouched in (invalid_id, unrelated_id):
                row = session.get(AuditEvent, untouched)
                assert row is not None and row.document_id is None
        with engine.begin() as connection:
            assert backfill_audit_document_ids(connection) == 0
    finally:
        with Session(engine) as session, session.begin():
            session.execute(
                delete(AuditEvent).where(AuditEvent.id.in_([legacy_id, invalid_id, unrelated_id]))
            )
        engine.dispose()


@postgres
def test_verified_source_backfill_marks_existing_money_as_reviewer_entered(
    make_tenant: TenantFactory,
) -> None:
    tenant = make_tenant()
    engine = owner_engine()
    document_id = uuid.uuid4()
    try:
        with Session(engine) as session, session.begin():
            session.add(
                Document(
                    id=document_id,
                    org_id=tenant.org_id,
                    uploaded_by=tenant.users["member"],
                    filename="legacy.pdf",
                    content_type="application/pdf",
                    size_bytes=10,
                    content_hash=document_id.hex,
                    storage_key=f"{tenant.org_id}/{document_id}.pdf",
                    workflow_config_version=1,
                    status="approved",
                )
            )
            session.flush()
            session.add(
                InvoiceMetadata(
                    document_id=document_id,
                    org_id=tenant.org_id,
                    verified_amount=Decimal("12.5000"),
                    currency="USD",
                    verified_source=None,
                )
            )
        with engine.begin() as connection:
            assert backfill_verified_source(connection) >= 1
        with Session(engine) as session:
            metadata = session.get(InvoiceMetadata, document_id)
            assert metadata is not None and metadata.verified_source == "reviewer"
        with engine.begin() as connection:
            assert backfill_verified_source(connection) == 0
    finally:
        engine.dispose()
