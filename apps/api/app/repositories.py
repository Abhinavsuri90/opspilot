import json
import uuid
from collections.abc import Iterable
from typing import Any, Literal

from sqlalchemy import ScalarSelect, Select, and_, exists, func, select
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.orm import Session, aliased

from app.access import accessible_document_clause
from app.action_models import (
    Action,
    ActionAttempt,
    ConnectorInstance,
    OrgActionPolicy,
    OrgSettings,
)
from app.intake_models import ApiKey, DocumentLink, EmailInbox, EmailMessage
from app.models import (
    AuditEvent,
    Document,
    ExtractedField,
    ExtractionRun,
    Membership,
    Organization,
    OutboxEvent,
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
    session: Session, org_id: uuid.UUID, document_id: uuid.UUID, *, lock: bool = False
) -> Document | None:
    query = select(Document).where(Document.org_id == org_id, Document.id == document_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    return session.scalar(query)


def get_outbox_event(
    session: Session, org_id: uuid.UUID, event_id: uuid.UUID, *, lock: bool = False
) -> OutboxEvent | None:
    query = select(OutboxEvent).where(OutboxEvent.org_id == org_id, OutboxEvent.id == event_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    return session.scalar(query)


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


# Governance: org switches, policies, connectors, actions and attempts.


def get_org_settings(
    session: Session, org_id: uuid.UUID, *, lock: Literal["share", "update"] | None = None
) -> OrgSettings | None:
    query = select(OrgSettings).where(OrgSettings.org_id == org_id)
    if lock == "share":
        query = query.with_for_update(read=True)
    elif lock == "update":
        query = query.with_for_update()
    return session.scalar(query)


def ensure_org_settings(session: Session, org_id: uuid.UUID) -> OrgSettings:
    """Read the row, creating it on first use; a concurrent creator wins harmlessly."""
    existing = get_org_settings(session, org_id)
    if existing is not None:
        return existing
    if session.get_bind().dialect.name == "postgresql":
        session.execute(
            postgresql.insert(OrgSettings).values(org_id=org_id).on_conflict_do_nothing()
        )
    else:
        session.execute(sqlite.insert(OrgSettings).values(org_id=org_id).on_conflict_do_nothing())
    created = get_org_settings(session, org_id)
    assert created is not None
    return created


def list_action_policies(session: Session, org_id: uuid.UUID) -> list[OrgActionPolicy]:
    return list(
        session.scalars(
            select(OrgActionPolicy)
            .where(OrgActionPolicy.org_id == org_id)
            .order_by(OrgActionPolicy.action_type)
        )
    )


def get_action_policy(
    session: Session, org_id: uuid.UUID, action_type: str, *, lock: bool = False
) -> OrgActionPolicy | None:
    query = select(OrgActionPolicy).where(
        OrgActionPolicy.org_id == org_id, OrgActionPolicy.action_type == action_type
    )
    if lock:
        query = query.with_for_update(read=True)
    return session.scalar(query)


def list_connectors(session: Session, org_id: uuid.UUID) -> list[ConnectorInstance]:
    return list(
        session.scalars(
            select(ConnectorInstance)
            .where(ConnectorInstance.org_id == org_id)
            .order_by(ConnectorInstance.name)
        )
    )


def get_connector_instance(
    session: Session, org_id: uuid.UUID, connector_id: uuid.UUID, *, lock: bool = False
) -> ConnectorInstance | None:
    query = select(ConnectorInstance).where(
        ConnectorInstance.org_id == org_id, ConnectorInstance.id == connector_id
    )
    if lock:
        query = query.with_for_update()
    return session.scalar(query)


def get_connector_by_name(
    session: Session, org_id: uuid.UUID, name: str
) -> ConnectorInstance | None:
    return session.scalar(
        select(ConnectorInstance).where(
            ConnectorInstance.org_id == org_id, ConnectorInstance.name == name
        )
    )


def get_action(
    session: Session, org_id: uuid.UUID, action_id: uuid.UUID, *, lock: bool = False
) -> Action | None:
    query = select(Action).where(Action.org_id == org_id, Action.id == action_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    return session.scalar(query)


def get_action_by_idempotency_key(
    session: Session, org_id: uuid.UUID, idempotency_key: str
) -> Action | None:
    return session.scalar(
        select(Action).where(Action.org_id == org_id, Action.idempotency_key == idempotency_key)
    )


def list_document_actions(
    session: Session, org_id: uuid.UUID, document_id: uuid.UUID, *, lock: bool = False
) -> list[Action]:
    query = (
        select(Action)
        .where(Action.org_id == org_id, Action.document_id == document_id)
        .order_by(Action.proposed_at, Action.id)
    )
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    return list(session.scalars(query))


def list_connector_actions(
    session: Session, org_id: uuid.UUID, connector_id: uuid.UUID, statuses: Iterable[str]
) -> list[Action]:
    """Actions bound to one connector in the given statuses, locked for a state change."""
    return list(
        session.scalars(
            select(Action)
            .where(
                Action.org_id == org_id,
                Action.connector_id == connector_id,
                Action.status.in_(list(statuses)),
            )
            .order_by(Action.proposed_at, Action.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    )


def list_action_attempts(
    session: Session, org_id: uuid.UUID, action_id: uuid.UUID
) -> list[ActionAttempt]:
    return list(
        session.scalars(
            select(ActionAttempt)
            .where(ActionAttempt.org_id == org_id, ActionAttempt.action_id == action_id)
            .order_by(ActionAttempt.attempt, ActionAttempt.started_at, ActionAttempt.id)
        )
    )


ActionRow = tuple[Action, Document, str | None, str | None]


def _action_rows_query(
    org_id: uuid.UUID, user_id: uuid.UUID, role: str
) -> Select[Action, Document, str, str]:
    decider = aliased(User)
    return (
        select(Action, Document, ConnectorInstance.name, decider.email)
        .join(Document, and_(Document.org_id == org_id, Document.id == Action.document_id))
        .outerjoin(
            ConnectorInstance,
            and_(
                ConnectorInstance.org_id == org_id,
                ConnectorInstance.id == Action.connector_id,
            ),
        )
        .outerjoin(decider, decider.id == Action.decided_by)
        .where(Action.org_id == org_id, accessible_document_clause(org_id, user_id, role))
    )


def list_accessible_actions(
    session: Session,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    role: str,
    *,
    status: str | None = None,
    document_id: uuid.UUID | None = None,
    offset: int = 0,
    limit: int = 50,
) -> list[ActionRow]:
    query = _action_rows_query(org_id, user_id, role)
    if status is not None:
        query = query.where(Action.status == status)
    if document_id is not None:
        query = query.where(Action.document_id == document_id)
    rows = session.execute(
        query.order_by(Action.proposed_at.desc(), Action.id.desc()).offset(offset).limit(limit)
    )
    return [(action, document, name, email) for action, document, name, email in rows]


def get_accessible_action(
    session: Session, org_id: uuid.UUID, user_id: uuid.UUID, role: str, action_id: uuid.UUID
) -> ActionRow | None:
    row = session.execute(
        _action_rows_query(org_id, user_id, role).where(Action.id == action_id)
    ).first()
    if row is None:
        return None
    action, document, name, email = row
    return action, document, name, email


def list_export_keys(session: Session, org_id: uuid.UUID, connector_id: uuid.UUID) -> list[str]:
    """Object keys written by succeeded CSV export actions of one connector."""
    rows = session.scalars(
        select(Action.result_json).where(
            Action.org_id == org_id,
            Action.connector_id == connector_id,
            Action.action_type == "export_csv",
            Action.status == "succeeded",
            Action.result_json.is_not(None),
        )
    )
    keys: list[str] = []
    for raw in rows:
        try:
            decoded = json.loads(raw or "{}")
        except ValueError:
            continue
        key = decoded.get("external_id") if isinstance(decoded, dict) else None
        if isinstance(key, str):
            keys.append(key)
    return keys


# Intake channels: document links, API keys, email inboxes and processed messages.


def list_document_links(
    session: Session, org_id: uuid.UUID, document_id: uuid.UUID
) -> list[DocumentLink]:
    return list(
        session.scalars(
            select(DocumentLink)
            .where(DocumentLink.org_id == org_id, DocumentLink.document_id == document_id)
            .order_by(DocumentLink.created_at, DocumentLink.id)
        )
    )


def list_near_duplicate_documents(
    session: Session,
    org_id: uuid.UUID,
    document_id: uuid.UUID,
    viewer: tuple[uuid.UUID, str] | None = None,
) -> list[Document]:
    """Documents linked to this one as near duplicates, limited to what the viewer may see."""
    query = (
        select(Document)
        .join(
            DocumentLink,
            and_(
                DocumentLink.org_id == org_id,
                DocumentLink.related_document_id == Document.id,
                DocumentLink.kind == "near_duplicate",
            ),
        )
        .where(Document.org_id == org_id, DocumentLink.document_id == document_id)
    )
    if viewer is not None:
        user_id, role = viewer
        query = query.where(accessible_document_clause(org_id, user_id, role))
    return list(session.scalars(query.order_by(Document.created_at, Document.id)))


def get_api_key_by_prefix(session: Session, key_prefix: str) -> ApiKey | None:
    """Prefix lookup; on Postgres the caller sets the prefix context first (see app.db)."""
    return session.scalar(select(ApiKey).where(ApiKey.key_prefix == key_prefix))


def get_api_key(
    session: Session, org_id: uuid.UUID, key_id: uuid.UUID, *, lock: bool = False
) -> ApiKey | None:
    query = select(ApiKey).where(ApiKey.org_id == org_id, ApiKey.id == key_id)
    if lock:
        query = query.with_for_update()
    return session.scalar(query)


def list_api_keys(session: Session, org_id: uuid.UUID) -> list[tuple[ApiKey, str | None]]:
    rows = session.execute(
        select(ApiKey, User.email)
        .outerjoin(User, User.id == ApiKey.created_by)
        .where(ApiKey.org_id == org_id)
        .order_by(ApiKey.created_at.desc(), ApiKey.id.desc())
    )
    return [(key, email) for key, email in rows]


def get_email_inbox(
    session: Session, org_id: uuid.UUID, *, lock: bool = False
) -> EmailInbox | None:
    query = select(EmailInbox).where(EmailInbox.org_id == org_id)
    if lock:
        query = query.with_for_update(skip_locked=True).execution_options(populate_existing=True)
    return session.scalar(query)


def get_email_message(session: Session, org_id: uuid.UUID, uid: str) -> EmailMessage | None:
    return session.scalar(
        select(EmailMessage).where(EmailMessage.org_id == org_id, EmailMessage.uid == uid)
    )


def email_message_totals(session: Session, org_id: uuid.UUID) -> tuple[int, int]:
    """(messages processed, documents created) for the organization's inbox."""
    row = session.execute(
        select(
            func.count(EmailMessage.id), func.coalesce(func.sum(EmailMessage.document_count), 0)
        ).where(EmailMessage.org_id == org_id)
    ).one()
    return int(row[0]), int(row[1])


def count_actions_by_status(
    session: Session, org_id: uuid.UUID, user_id: uuid.UUID, role: str
) -> dict[str, int]:
    rows = session.execute(
        select(Action.status, func.count(Action.id))
        .join(Document, and_(Document.org_id == org_id, Document.id == Action.document_id))
        .where(Action.org_id == org_id, accessible_document_clause(org_id, user_id, role))
        .group_by(Action.status)
    )
    return {str(status): int(count) for status, count in rows}
