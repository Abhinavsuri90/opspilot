"""Small Postgres outbox worker for the first document workflow slice."""

import json
import logging
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, or_, select, update

from app.db import SessionLocal, set_org_context
from app.llm.provider import (
    ExtractedValue,
    ExtractionError,
    ExtractionProvider,
    ProviderUnavailable,
    get_provider,
)
from app.models import (
    AuditEvent,
    Document,
    ExtractedField,
    ExtractionRun,
    Organization,
    OutboxEvent,
)
from app.storage import ObjectStore, StorageError, get_store

logger = logging.getLogger(__name__)
MAX_EXTRACTION_ATTEMPTS = 3


@dataclass(frozen=True)
class Claim:
    org_id: uuid.UUID
    event_id: uuid.UUID
    document_id: uuid.UUID
    storage_key: str
    claimed_at: datetime
    attempts: int


def audit(org_id: uuid.UUID, document_id: uuid.UUID, event_type: str) -> AuditEvent:
    return AuditEvent(
        id=uuid.uuid4(),
        org_id=org_id,
        actor_user_id=None,
        event_type=event_type,
        detail_json=json.dumps({"document_id": str(document_id)}),
    )


def claim_next(org_id: uuid.UUID, document_id: uuid.UUID | None = None) -> Claim | None:
    now = datetime.now(UTC)
    stale_before = now - timedelta(minutes=5)
    with SessionLocal() as session, session.begin():
        set_org_context(session, org_id)
        statement = (
            select(OutboxEvent, Document)
            .join(Document, Document.id == OutboxEvent.document_id)
            .where(
                OutboxEvent.org_id == org_id,
                Document.org_id == org_id,
                OutboxEvent.topic == "extract_document",
                OutboxEvent.published_at.is_(None),
                OutboxEvent.available_at <= now,
                or_(
                    Document.status == "queued",
                    and_(Document.status == "extracting", OutboxEvent.claimed_at < stale_before),
                ),
            )
            .order_by(OutboxEvent.created_at, OutboxEvent.id)
            .with_for_update(of=OutboxEvent, skip_locked=True)
            .limit(1)
        )
        if document_id is not None:
            statement = statement.where(Document.id == document_id)
        row = session.execute(statement).first()
        if row is None:
            return None
        event, document = row
        changed = session.scalar(
            update(Document)
            .where(
                Document.id == document.id,
                Document.org_id == org_id,
                Document.status == document.status,
            )
            .values(status="extracting", updated_at=now)
            .returning(Document.id)
        )
        if changed is None:
            return None
        event.claimed_at = now
        event.attempts += 1
        session.add(audit(org_id, document.id, "document.extracting"))
        return Claim(org_id, event.id, document.id, document.storage_key, now, event.attempts)


def complete(claim: Claim, fields: list[ExtractedValue], provider: ExtractionProvider) -> None:
    with SessionLocal() as session, session.begin():
        set_org_context(session, claim.org_id)
        # Serialize completion with lease reclamation. Reading the lease without
        # a lock can let an old worker commit after another worker reclaims it.
        event = session.get(OutboxEvent, claim.event_id, with_for_update=True)
        document = session.get(Document, claim.document_id, with_for_update=True)
        if (
            event is None
            or document is None
            or event.claimed_at != claim.claimed_at
            or event.published_at is not None
            or document.status != "extracting"
        ):
            return
        run = ExtractionRun(
            id=uuid.uuid4(),
            org_id=claim.org_id,
            document_id=claim.document_id,
            provider=provider.name,
            model=provider.model,
            prompt_version=provider.prompt_version,
            raw_json=json.dumps([asdict(field) for field in fields]),
        )
        session.add(run)
        session.flush()
        for field in fields:
            session.add(
                ExtractedField(
                    id=uuid.uuid4(),
                    org_id=claim.org_id,
                    document_id=claim.document_id,
                    extraction_run_id=run.id,
                    name=field.name,
                    value=field.value,
                    evidence=field.evidence,
                    page_number=field.page_number,
                )
            )
        document.status = "needs_review"
        document.failure_reason = None
        document.updated_at = datetime.now(UTC)
        event.published_at = datetime.now(UTC)
        session.add(audit(claim.org_id, claim.document_id, "document.needs_review"))


def fail(claim: Claim, reason: str, retryable: bool) -> None:
    now = datetime.now(UTC)
    with SessionLocal() as session, session.begin():
        set_org_context(session, claim.org_id)
        event = session.get(OutboxEvent, claim.event_id, with_for_update=True)
        document = session.get(Document, claim.document_id, with_for_update=True)
        if (
            event is None
            or document is None
            or event.claimed_at != claim.claimed_at
            or event.published_at is not None
            or document.status != "extracting"
        ):
            return
        document.updated_at = now
        if retryable and claim.attempts < MAX_EXTRACTION_ATTEMPTS:
            document.status = "queued"
            event.available_at = now + timedelta(seconds=2**claim.attempts)
            event.claimed_at = None
            session.add(audit(claim.org_id, claim.document_id, "document.retry_scheduled"))
        else:
            document.status = "failed"
            document.failure_reason = reason[:200]
            event.published_at = now
            session.add(audit(claim.org_id, claim.document_id, "document.failed"))


def process_one(
    store: ObjectStore | None = None, document_id: uuid.UUID | None = None
) -> bool:
    object_store = store or get_store()
    provider = get_provider()
    with SessionLocal() as session:
        org_ids = list(session.scalars(select(Organization.id).order_by(Organization.id)))
    for org_id in org_ids:
        claim = claim_next(org_id, document_id)
        if claim is None:
            continue
        if claim.attempts > MAX_EXTRACTION_ATTEMPTS:
            fail(
                claim,
                "Extraction attempt limit reached after worker interruption",
                retryable=False,
            )
            return True
        try:
            data = object_store.get(claim.storage_key)
            fields = provider.extract(data)
        except ExtractionError as exc:
            fail(claim, str(exc), retryable=False)
        except (StorageError, ProviderUnavailable):
            fail(claim, "Storage or extraction provider was unavailable", retryable=True)
        except Exception:
            logger.exception("Unexpected extraction error for document %s", claim.document_id)
            fail(claim, "Extraction failed after retries", retryable=True)
        else:
            complete(claim, fields, provider)
        return True
    return False


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    # Invalid provider configuration is a deployment error, not a recoverable
    # document error. Let the process exit so the platform reports it clearly.
    get_provider()
    while True:
        try:
            worked = process_one()
        except Exception:
            logger.exception("Worker loop failed; retrying")
            worked = False
        if not worked:
            time.sleep(2)


if __name__ == "__main__":
    main()
