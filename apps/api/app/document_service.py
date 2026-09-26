import hashlib
import json
import uuid
from datetime import datetime

from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import set_org_context
from app.models import AuditEvent, Document, ExtractedField, OutboxEvent
from app.repositories import (
    get_document_by_hash,
    get_document_by_id,
    latest_extraction_run,
    latest_workflow_config,
    list_document_fields,
    list_documents,
)
from app.storage import ObjectStore

MAX_UPLOAD_BYTES = 10 * 1024 * 1024


class InvalidDocument(Exception):
    pass


class MissingWorkflowConfig(Exception):
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
) -> UploadResponse:
    if not data or len(data) > MAX_UPLOAD_BYTES:
        raise InvalidDocument("PDF must be between 1 byte and 10 MB")
    if not data.startswith(b"%PDF-"):
        raise InvalidDocument("Only PDF files are supported in this demo")

    safe_name = filename.replace("\\", "/").split("/")[-1][:255] or "document.pdf"
    digest = hashlib.sha256(data).hexdigest()
    existing = get_document_by_hash(session, org_id, digest)
    if existing is not None:
        return UploadResponse(**summary(existing).model_dump(), duplicate=True)

    config = latest_workflow_config(session, org_id)
    if config is None:
        raise MissingWorkflowConfig("No workflow configuration exists for this organization")

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
        return UploadResponse(**summary(existing).model_dump(), duplicate=True)
    return UploadResponse(**summary(document).model_dump(), duplicate=False)


def browse(session: Session, org_id: uuid.UUID) -> list[DocumentSummary]:
    return [summary(document) for document in list_documents(session, org_id)]


def read(session: Session, org_id: uuid.UUID, document_id: uuid.UUID) -> DocumentDetail | None:
    document = get_document_by_id(session, org_id, document_id)
    if document is None:
        return None
    run = latest_extraction_run(session, org_id, document_id)
    return detail(
        document,
        list_document_fields(session, org_id, document_id),
        run.provider if run is not None else None,
    )
