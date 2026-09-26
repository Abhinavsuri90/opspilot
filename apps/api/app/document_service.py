import hashlib
import json
import uuid
from datetime import UTC, datetime

from pydantic import BaseModel
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import set_org_context
from app.invoice_workflows import accessible_document_clause, can_access_document
from app.limits import MAX_UPLOAD_BYTES
from app.llm.provider import ExtractionError, pdf_pages
from app.models import AuditEvent, Document, ExtractedField, OutboxEvent
from app.repositories import (
    get_document_by_hash,
    get_document_by_id,
    latest_extraction_run,
    latest_workflow_config,
    list_document_fields,
)
from app.storage import ObjectStore
from app.workflow_models import InvoiceMetadata

MAX_MANUAL_RETRIES = 2


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
    size_bytes: int
    workflow_config_version: int
    failure_reason: str | None
    created_at: datetime


class FieldResponse(BaseModel):
    name: str
    value: str
    evidence: str
    page_number: int


class DocumentDetail(DocumentSummary):
    fields: list[FieldResponse]
    provider: str | None


class UploadResponse(DocumentSummary):
    duplicate: bool


def summary(document: Document) -> DocumentSummary:
    return DocumentSummary(
        id=document.id,
        filename=document.filename,
        status=document.status,
        size_bytes=document.size_bytes,
        workflow_config_version=document.workflow_config_version,
        failure_reason=document.failure_reason,
        created_at=document.created_at,
    )


def detail(
    document: Document, fields: list[ExtractedField], provider: str | None
) -> DocumentDetail:
    return DocumentDetail(
        **summary(document).model_dump(),
        provider=provider,
        fields=[
            FieldResponse(
                name=field.name,
                value=field.value,
                evidence=field.evidence,
                page_number=field.page_number,
            )
            for field in fields
        ],
    )


def upload(
    session: Session,
    store: ObjectStore,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    filename: str,
    data: bytes,
    role: str = "member",
) -> UploadResponse:
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
        pdf_pages(data)
    except ExtractionError as exc:
        raise InvalidDocument(str(exc)) from exc

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
    for event_type in ("document.received", "document.queued"):
        session.add(
            AuditEvent(
                id=uuid.uuid4(),
                org_id=org_id,
                actor_user_id=user_id,
                event_type=event_type,
                detail_json=json.dumps({"document_id": str(document.id)}),
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
) -> list[DocumentSummary]:
    query = select(Document).where(accessible_document_clause(org_id, user_id, role))
    if status == "in_progress":
        query = query.where(Document.status.in_(("queued", "extracting", "validating")))
    elif status:
        query = query.where(Document.status == status)
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
    documents = session.scalars(
        query.order_by(Document.created_at.desc(), Document.id.desc()).offset(offset).limit(limit)
    )
    return [summary(document) for document in documents]


def read(
    session: Session,
    org_id: uuid.UUID,
    document_id: uuid.UUID,
    user_id: uuid.UUID,
    role: str,
) -> DocumentDetail | None:
    document = get_document_by_id(session, org_id, document_id)
    if document is None or not can_access_document(session, org_id, user_id, role, document):
        return None
    run = latest_extraction_run(session, org_id, document_id)
    return detail(
        document,
        list_document_fields(session, org_id, document_id),
        run.provider if run is not None else None,
    )


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
    session.add(
        AuditEvent(
            id=uuid.uuid4(),
            org_id=org_id,
            actor_user_id=user_id,
            event_type="document.retry_requested",
            detail_json=json.dumps({"document_id": str(document.id)}),
        )
    )
    session.commit()
    return summary(document)
