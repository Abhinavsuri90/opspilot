import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Document,
    ExtractedField,
    ExtractionRun,
    Membership,
    Organization,
    User,
    WorkflowConfig,
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


def list_documents(session: Session, org_id: uuid.UUID) -> list[Document]:
    return list(
        session.scalars(
            select(Document)
            .where(Document.org_id == org_id)
            .order_by(Document.created_at.desc(), Document.id.desc())
            .limit(50)
        )
    )


def list_document_fields(
    session: Session, org_id: uuid.UUID, document_id: uuid.UUID
) -> list[ExtractedField]:
    return list(
        session.scalars(
            select(ExtractedField)
            .where(ExtractedField.org_id == org_id, ExtractedField.document_id == document_id)
            .order_by(ExtractedField.name)
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
