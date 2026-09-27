import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.access import accessible_document_clause, can_access_document
from app.config import get_settings
from app.db import set_org_context
from app.limits import MAX_UPLOAD_BYTES
from app.llm.provider import ExtractionError, pdf_pages
from app.models import AuditEvent, Document, OutboxEvent
from app.repositories import (
    flagged_counts,
    get_document_by_hash,
    latest_workflow_config,
)
from app.storage import ObjectStore
from app.timeouts import OperationTimeout, run_with_timeout
from app.workflow_models import InvoiceMetadata

MAX_MANUAL_RETRIES = 2
# Email body text kept with a document as reviewer context; longer bodies are cut.
MAX_CONTEXT_CHARS = 20_000
MAX_SOURCE_REF_CHARS = 300
DocumentSource = Literal["upload", "email", "api"]


class DocumentAccessDenied(Exception):
    pass


class InvalidDocument(Exception):
    pass


class MissingWorkflowConfig(Exception):
    pass


class DocumentLimitReached(Exception):
    pass


class DocumentNotRetryable(Exception):
    pass


class DocumentRetryLimitReached(Exception):
    pass


class DocumentSummary(BaseModel):
    id: uuid.UUID
    filename: str
    status: str
    document_type: str
    source: str
    source_ref: str | None
    size_bytes: int
    workflow_config_version: int
    failure_reason: str | None
    flagged_count: int
    created_at: datetime


class UploadResponse(DocumentSummary):
    duplicate: bool


def summary(document: Document, flagged_count: int = 0) -> DocumentSummary:
    return DocumentSummary(
        id=document.id,
        filename=document.filename,
        status=document.status,
        document_type=document.document_type,
        source=document.source,
        source_ref=document.source_ref,
        size_bytes=document.size_bytes,
        workflow_config_version=document.workflow_config_version,
        failure_reason=document.failure_reason,
        flagged_count=flagged_count,
        created_at=document.created_at,
    )


def document_audit(
    org_id: uuid.UUID,
    document_id: uuid.UUID,
    actor_user_id: uuid.UUID | None,
    event_type: str,
    detail: dict[str, object] | None = None,
    created_at: datetime | None = None,
) -> AuditEvent:
    """Audit row for a document event; document_id is indexed for the timeline.

    The timestamp comes from the application clock: rows written in one database
    transaction would otherwise share the same ``now()`` and lose their order.
    """
    payload: dict[str, object] = {"document_id": str(document_id), **(detail or {})}
    return AuditEvent(
        id=uuid.uuid4(),
        org_id=org_id,
        actor_user_id=actor_user_id,
        document_id=document_id,
        event_type=event_type,
        detail_json=json.dumps(payload, default=str, sort_keys=True),
        created_at=created_at or datetime.now(UTC),
    )


def upload(
    session: Session,
    store: ObjectStore,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    filename: str,
    data: bytes,
    role: str = "member",
    *,
    source: DocumentSource = "upload",
    source_ref: str | None = None,
    context_text: str | None = None,
    audit_actor: uuid.UUID | None | Literal["uploader"] = "uploader",
    audit_detail: dict[str, object] | None = None,
) -> UploadResponse:
    """Store a PDF and queue extraction.

    ``user_id`` is the document owner (``uploaded_by``). Intake channels pass their own
    ``source``: the API key path audits with the key's creator plus the key id, email intake
    audits as the system (``audit_actor=None``) with the message uid.
    """
    actor_user_id = user_id if audit_actor == "uploader" else audit_actor
    if not data or len(data) > MAX_UPLOAD_BYTES:
        raise InvalidDocument("PDF must be between 1 byte and 10 MB")
    if not data.startswith(b"%PDF-"):
        raise InvalidDocument("Only PDF files are supported")

    basename = filename.replace("\\", "/").split("/")[-1]
    safe_name = "".join(char if char.isprintable() else "_" for char in basename)[:255]
    safe_name = safe_name or "document.pdf"
    digest = hashlib.sha256(data).hexdigest()
    existing = get_document_by_hash(session, org_id, digest)
    if existing is not None:
        if not can_access_document(session, org_id, user_id, role, existing):
            raise DocumentAccessDenied("This file already exists and is not accessible") from None
        return UploadResponse(**summary(existing).model_dump(), duplicate=True)

    try:
        run_with_timeout(lambda: pdf_pages(data), get_settings().upload_parse_timeout_seconds)
    except ExtractionError as exc:
        raise InvalidDocument(str(exc)) from exc
    except OperationTimeout as exc:
        raise InvalidDocument("PDF took too long to parse") from exc

    config = latest_workflow_config(session, org_id)
    if config is None:
        raise MissingWorkflowConfig("No workflow configuration exists for this organization")

    # Serialize the quota decision with uploads to this tenant. The lock is
    # released when the document/outbox transaction commits or rolls back.
    lock_id = int.from_bytes(org_id.bytes[:8], byteorder="big", signed=True)
    session.scalar(text("SELECT pg_advisory_xact_lock(:lock_id)"), {"lock_id": lock_id})
    existing = get_document_by_hash(session, org_id, digest)
    if existing is not None:
        if not can_access_document(session, org_id, user_id, role, existing):
            raise DocumentAccessDenied("This file already exists and is not accessible") from None
        return UploadResponse(**summary(existing).model_dump(), duplicate=True)
    count = session.scalar(
        select(func.count()).select_from(Document).where(Document.org_id == org_id)
    )
    if (count or 0) >= get_settings().max_documents_per_org:
        raise DocumentLimitReached("This organization has reached its document limit")

    # Deterministic key makes concurrent duplicate uploads safe to retry.
    key = f"{org_id}/{digest}.pdf"
    store.put(key, data)
    document = Document(
        id=uuid.uuid4(),
        org_id=org_id,
        uploaded_by=user_id,
        filename=safe_name,
        content_type="application/pdf",
        size_bytes=len(data),
        content_hash=digest,
        storage_key=key,
        workflow_config_version=config.version,
        status="queued",
        source=source,
        source_ref=source_ref[:MAX_SOURCE_REF_CHARS] if source_ref else None,
        context_text=context_text[:MAX_CONTEXT_CHARS] if context_text else None,
    )
    session.add(document)
    session.add(
        OutboxEvent(
            id=uuid.uuid4(),
            org_id=org_id,
            document_id=document.id,
            topic="extract_document",
            payload_json=json.dumps({"document_id": str(document.id)}),
            attempts=0,
        )
    )
    received_at = datetime.now(UTC)
    detail: dict[str, object] = {"source": source, **(audit_detail or {})}
    for order, event_type in enumerate(("document.received", "document.queued")):
        session.add(
            document_audit(
                org_id,
                document.id,
                actor_user_id,
                event_type,
                detail,
                created_at=received_at + timedelta(microseconds=order),
            )
        )
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        set_org_context(session, org_id)
        existing = get_document_by_hash(session, org_id, digest)
        if existing is None:
            raise
        if not can_access_document(session, org_id, user_id, role, existing):
            raise DocumentAccessDenied("This file already exists and is not accessible") from None
        return UploadResponse(**summary(existing).model_dump(), duplicate=True)
    return UploadResponse(**summary(document).model_dump(), duplicate=False)


def browse(
    session: Session,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    role: str,
    *,
    offset: int = 0,
    limit: int = 50,
    status: str | None = None,
    category_id: uuid.UUID | None = None,
    q: str | None = None,
    document_type: str | None = None,
    source: str | None = None,
) -> list[DocumentSummary]:
    query = select(Document).where(accessible_document_clause(org_id, user_id, role))
    if status == "in_progress":
        query = query.where(Document.status.in_(("queued", "extracting", "validating")))
    elif status:
        query = query.where(Document.status == status)
    if document_type:
        query = query.where(Document.document_type == document_type)
    if source:
        query = query.where(Document.source == source)
    if category_id:
        query = query.where(
            Document.id.in_(
                select(InvoiceMetadata.document_id).where(
                    InvoiceMetadata.org_id == org_id, InvoiceMetadata.category_id == category_id
                )
            )
        )
    if q:
        query = query.where(Document.filename.icontains(q, autoescape=True))
    documents = list(
        session.scalars(
            query.order_by(Document.created_at.desc(), Document.id.desc())
            .offset(offset)
            .limit(limit)
        )
    )
    flagged = flagged_counts(session, org_id, [document.id for document in documents])
    return [summary(document, flagged.get(document.id, 0)) for document in documents]


def retry(
    session: Session,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    document_id: uuid.UUID,
    role: str = "member",
) -> DocumentSummary | None:
    document = session.scalar(
        select(Document)
        .where(Document.org_id == org_id, Document.id == document_id)
        .with_for_update()
    )
    if document is None or not can_access_document(session, org_id, user_id, role, document):
        return None
    if document.status != "failed":
        raise DocumentNotRetryable("Only failed documents can be retried")

    # The initial upload creates one outbox event. Every manual retry creates
    # another; automatic worker attempts reuse their event. The document lock
    # above serializes this count and the following insert across API instances.
    event_count = session.scalar(
        select(func.count())
        .select_from(OutboxEvent)
        .where(
            OutboxEvent.org_id == org_id,
            OutboxEvent.document_id == document_id,
            OutboxEvent.topic == "extract_document",
        )
    )
    if (event_count or 0) > MAX_MANUAL_RETRIES:
        raise DocumentRetryLimitReached("Manual retry limit reached for this document")

    document.status = "queued"
    document.failure_reason = None
    document.updated_at = datetime.now(UTC)
    session.add(
        OutboxEvent(
            id=uuid.uuid4(),
            org_id=org_id,
            document_id=document.id,
            topic="extract_document",
            payload_json=json.dumps({"document_id": str(document.id)}),
            attempts=0,
        )
    )
    session.add(document_audit(org_id, document.id, user_id, "document.retry_requested"))
    session.commit()
    return summary(document)
