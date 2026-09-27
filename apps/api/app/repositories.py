import uuid
from collections.abc import Iterable
from typing import Any

from sqlalchemy import ScalarSelect, exists, func, select
from sqlalchemy.orm import Session, aliased

from app.models import (
    AuditEvent,
    Document,
    ExtractedField,
    ExtractionRun,
    Membership,
    Organization,
    User,
    WorkflowConfig,
)
from app.workflow_models import (
    FieldCorrection,
    InvoiceComment,
    InvoiceReview,
    ReviewTask,
)


def get_organization_by_slug(session: Session, slug: str) -> Organization | None:
    return session.scalar(select(Organization).where(Organization.slug == slug))


def get_user_by_email(session: Session, email: str) -> User | None:
    return session.scalar(select(User).where(User.email == email))


def get_user_by_id(session: Session, user_id: uuid.UUID) -> User | None:
    return session.scalar(select(User).where(User.id == user_id))


def get_organization_by_id(session: Session, org_id: uuid.UUID) -> Organization | None:
    return session.scalar(select(Organization).where(Organization.id == org_id))


def get_membership(session: Session, org_id: uuid.UUID, user_id: uuid.UUID) -> Membership | None:
    return session.scalar(
        select(Membership).where(Membership.org_id == org_id, Membership.user_id == user_id)
    )


def list_members(session: Session, org_id: uuid.UUID) -> list[tuple[Membership, User]]:
    rows = session.execute(
        select(Membership, User)
        .join(User, User.id == Membership.user_id)
        .where(Membership.org_id == org_id)
        .order_by(User.email)
    )
    return [(membership, user) for membership, user in rows]


def latest_workflow_config(session: Session, org_id: uuid.UUID) -> WorkflowConfig | None:
    return session.scalar(
        select(WorkflowConfig)
        .where(WorkflowConfig.org_id == org_id)
        .order_by(WorkflowConfig.version.desc())
        .limit(1)
    )


def get_workflow_config_version(
    session: Session, org_id: uuid.UUID, version: int
) -> WorkflowConfig | None:
    return session.scalar(
        select(WorkflowConfig).where(
            WorkflowConfig.org_id == org_id, WorkflowConfig.version == version
        )
    )


def get_document_by_hash(session: Session, org_id: uuid.UUID, digest: str) -> Document | None:
    return session.scalar(
        select(Document).where(Document.org_id == org_id, Document.content_hash == digest)
    )


def get_document_by_id(
    session: Session, org_id: uuid.UUID, document_id: uuid.UUID
) -> Document | None:
    return session.scalar(
        select(Document).where(Document.org_id == org_id, Document.id == document_id)
    )


def list_document_fields(
    session: Session,
    org_id: uuid.UUID,
    document_id: uuid.UUID,
    extraction_run_id: uuid.UUID | None = None,
) -> list[ExtractedField]:
    query = select(ExtractedField).where(
        ExtractedField.org_id == org_id, ExtractedField.document_id == document_id
    )
    if extraction_run_id is not None:
        query = query.where(ExtractedField.extraction_run_id == extraction_run_id)
    return list(session.scalars(query.order_by(ExtractedField.name, ExtractedField.id)))


def get_extracted_field(
    session: Session, org_id: uuid.UUID, document_id: uuid.UUID, field_id: uuid.UUID
) -> ExtractedField | None:
    return session.scalar(
        select(ExtractedField).where(
            ExtractedField.org_id == org_id,
            ExtractedField.document_id == document_id,
            ExtractedField.id == field_id,
        )
    )


def latest_extraction_run(
    session: Session, org_id: uuid.UUID, document_id: uuid.UUID
) -> ExtractionRun | None:
    return session.scalar(
        select(ExtractionRun)
        .where(ExtractionRun.org_id == org_id, ExtractionRun.document_id == document_id)
        .order_by(ExtractionRun.created_at.desc(), ExtractionRun.id.desc())
        .limit(1)
    )


def list_extraction_runs(
    session: Session, org_id: uuid.UUID, document_id: uuid.UUID
) -> list[ExtractionRun]:
    return list(
        session.scalars(
            select(ExtractionRun)
            .where(ExtractionRun.org_id == org_id, ExtractionRun.document_id == document_id)
            .order_by(ExtractionRun.created_at, ExtractionRun.id)
        )
    )


def list_field_corrections(
    session: Session, org_id: uuid.UUID, document_id: uuid.UUID
) -> list[tuple[FieldCorrection, str]]:
    """Corrections for a document in the order they were made, with reviewer emails."""
    rows = session.execute(
        select(FieldCorrection, User.email)
        .join(User, User.id == FieldCorrection.reviewer_user_id)
        .where(FieldCorrection.org_id == org_id, FieldCorrection.document_id == document_id)
        .order_by(FieldCorrection.created_at, FieldCorrection.id)
    )
    return [(correction, email) for correction, email in rows]


def get_review_task(
    session: Session, org_id: uuid.UUID, document_id: uuid.UUID, *, lock: bool = False
) -> ReviewTask | None:
    query = select(ReviewTask).where(
        ReviewTask.org_id == org_id, ReviewTask.document_id == document_id
    )
    if lock:
        query = query.with_for_update()
    return session.scalar(query)


def latest_run_id_for(org_id: uuid.UUID, document_id_column: Any) -> ScalarSelect[Any]:
    """Correlated subquery: id of the newest extraction run for the given document column."""
    run = aliased(ExtractionRun)
    return (
        select(run.id)
        .where(run.org_id == org_id, run.document_id == document_id_column)
        .order_by(run.created_at.desc(), run.id.desc())
        .limit(1)
        .scalar_subquery()
    )


def flagged_counts(
    session: Session, org_id: uuid.UUID, document_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, int]:
    """Count still-flagged fields of the latest run per document in one grouped query."""
    ids = list(document_ids)
    if not ids:
        return {}
    corrected = (
        exists()
        .where(
            FieldCorrection.field_id == ExtractedField.id,
            FieldCorrection.org_id == org_id,
        )
        .correlate(ExtractedField)
    )
    latest_run = latest_run_id_for(org_id, ExtractedField.document_id).correlate(ExtractedField)
    rows = session.execute(
        select(ExtractedField.document_id, func.count(ExtractedField.id))
        .where(
            ExtractedField.org_id == org_id,
            ExtractedField.document_id.in_(ids),
            ExtractedField.extraction_run_id == latest_run,
            ExtractedField.status == "needs_review",
            ~corrected,
        )
        .group_by(ExtractedField.document_id)
    )
    return {document_id: int(count) for document_id, count in rows}


def list_document_audit_events(
    session: Session, org_id: uuid.UUID, document_id: uuid.UUID
) -> list[tuple[AuditEvent, str | None]]:
    rows = session.execute(
        select(AuditEvent, User.email)
        .outerjoin(User, User.id == AuditEvent.actor_user_id)
        .where(AuditEvent.org_id == org_id, AuditEvent.document_id == document_id)
        .order_by(AuditEvent.created_at, AuditEvent.id)
    )
    return [(event, email) for event, email in rows]


def list_document_reviews(
    session: Session, org_id: uuid.UUID, document_id: uuid.UUID
) -> list[tuple[InvoiceReview, str]]:
    rows = session.execute(
        select(InvoiceReview, User.email)
        .join(User, User.id == InvoiceReview.actor_user_id)
        .where(InvoiceReview.org_id == org_id, InvoiceReview.document_id == document_id)
        .order_by(InvoiceReview.created_at, InvoiceReview.id)
    )
    return [(review, email) for review, email in rows]


def list_document_comments(
    session: Session, org_id: uuid.UUID, document_id: uuid.UUID
) -> list[tuple[InvoiceComment, str]]:
    rows = session.execute(
        select(InvoiceComment, User.email)
        .join(User, User.id == InvoiceComment.author_user_id)
        .where(InvoiceComment.org_id == org_id, InvoiceComment.document_id == document_id)
        .order_by(InvoiceComment.created_at, InvoiceComment.id)
    )
    return [(comment, email) for comment, email in rows]
