"""Document access predicates shared by lists, aggregates and every direct document read."""

import uuid

from sqlalchemy import and_, exists, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.models import Document
from app.workflow_models import InvoiceGrant, InvoiceMetadata


def accessible_document_clause(
    org_id: uuid.UUID, user_id: uuid.UUID, role: str
) -> ColumnElement[bool]:
    """SQL predicate shared by lists, aggregates and direct document access."""
    tenant = Document.org_id == org_id
    if role == "admin":
        return tenant
    restricted = (
        exists()
        .where(
            InvoiceMetadata.document_id == Document.id,
            InvoiceMetadata.org_id == org_id,
            InvoiceMetadata.visibility == "restricted",
        )
        .correlate(Document)
    )
    assigned = (
        exists()
        .where(
            InvoiceMetadata.document_id == Document.id,
            InvoiceMetadata.org_id == org_id,
            InvoiceMetadata.assigned_reviewer_id == user_id,
        )
        .correlate(Document)
    )
    granted = (
        exists()
        .where(
            InvoiceGrant.document_id == Document.id,
            InvoiceGrant.org_id == org_id,
            InvoiceGrant.user_id == user_id,
        )
        .correlate(Document)
    )
    return and_(tenant, or_(~restricted, Document.uploaded_by == user_id, assigned, granted))


def can_access_document(
    session: Session, org_id: uuid.UUID, user_id: uuid.UUID, role: str, document: Document
) -> bool:
    if document.org_id != org_id:
        return False
    return (
        session.scalar(
            select(Document.id).where(
                Document.id == document.id, accessible_document_clause(org_id, user_id, role)
            )
        )
        is not None
    )
