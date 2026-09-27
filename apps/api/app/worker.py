"""Postgres outbox worker: extraction, validation, confidence and review routing."""

import hashlib
import json
import logging
import time
import uuid
from bisect import bisect
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from functools import partial

from sqlalchemy import and_, or_, select, update
from sqlalchemy.orm import Session

from app.confidence import Evaluation, evaluate
from app.config import get_settings
from app.db import SessionLocal, set_org_context
from app.document_service import document_audit
from app.llm.provider import (
    ExtractionError,
    ExtractionProvider,
    ExtractionResult,
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
from app.repositories import get_workflow_config_version
from app.review_service import open_review_task
from app.storage import ObjectStore, StorageError, StoredDocumentTooLarge, get_store
from app.timeouts import OperationTimeout, ParserBusy, run_with_timeout
from app.workflow_config import (
    DocumentTypeSpec,
    InvalidWorkflowConfig,
    WorkflowConfigModel,
    load_config,
)

logger = logging.getLogger(__name__)
MAX_EXTRACTION_ATTEMPTS = 3
# A claim older than this can be taken over by another worker. It must exceed the
# extraction timeout, or a slow-but-alive worker could be reclaimed mid-flight.
STALE_LEASE_FLOOR_SECONDS = 300
_last_org_id: uuid.UUID | None = None


def stale_lease_seconds() -> int:
    return max(STALE_LEASE_FLOOR_SECONDS, int(get_settings().extraction_timeout_seconds) + 60)


@dataclass(frozen=True)
class Claim:
    org_id: uuid.UUID
    event_id: uuid.UUID
    document_id: uuid.UUID
    storage_key: str
    content_hash: str
    size_bytes: int
    claimed_at: datetime
    attempts: int
    workflow_config_version: int


def audit(
    org_id: uuid.UUID,
    document_id: uuid.UUID,
    event_type: str,
    detail: dict[str, object] | None = None,
    created_at: datetime | None = None,
) -> AuditEvent:
    return document_audit(org_id, document_id, None, event_type, detail, created_at)


def claim_next(org_id: uuid.UUID, document_id: uuid.UUID | None = None) -> Claim | None:
    now = datetime.now(UTC)
    stale_before = now - timedelta(seconds=stale_lease_seconds())
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
        return Claim(
            org_id,
            event.id,
            document.id,
            document.storage_key,
            document.content_hash,
            document.size_bytes,
            now,
            event.attempts,
            document.workflow_config_version,
        )


def load_pinned_config(org_id: uuid.UUID, version: int) -> WorkflowConfigModel | None:
    with SessionLocal() as session:
        set_org_context(session, org_id)
        row = get_workflow_config_version(session, org_id, version)
        if row is None:
            return None
        try:
            return load_config(row.config_json)
        except InvalidWorkflowConfig:
            logger.warning("Workflow config version %s for org %s is invalid", version, org_id)
            return None


def _current_lease(session: Session, claim: Claim) -> tuple[OutboxEvent, Document] | None:
    """Lock the outbox event and document; None when another worker reclaimed the lease."""
    event = session.get(OutboxEvent, claim.event_id, with_for_update=True)
    document = session.get(Document, claim.document_id, with_for_update=True)
    if (
        event is None
        or document is None
        or event.claimed_at != claim.claimed_at
        or event.published_at is not None
        or document.status != "extracting"
    ):
        return None
    return event, document


def _store_run(
    claim: Claim,
    result: ExtractionResult,
    provider: ExtractionProvider,
    evaluation: Evaluation,
    created_at: datetime,
) -> tuple[ExtractionRun, list[ExtractedField]]:
    run = ExtractionRun(
        id=uuid.uuid4(),
        org_id=claim.org_id,
        document_id=claim.document_id,
        provider=provider.name,
        model=result.model,
        prompt_version=result.prompt_version,
        created_at=created_at,
        raw_json=json.dumps(
            {
                "fields": [asdict(value) for value in result.fields],
                "document_type": result.document_type,
                "tokens_in": result.tokens_in,
                "tokens_out": result.tokens_out,
                "latency_ms": result.latency_ms,
                "notes": result.notes,
                "rule_results": [asdict(rule) for rule in evaluation.rule_results],
            }
        ),
    )
    fields = [
        ExtractedField(
            id=uuid.uuid4(),
            org_id=claim.org_id,
            document_id=claim.document_id,
            extraction_run_id=run.id,
            name=assessment.name,
            value=assessment.value,
            evidence=assessment.evidence,
            page_number=assessment.page_number,
            field_type=assessment.field_type,
            required=assessment.required,
            confidence=_decimal4(assessment.confidence),
            threshold=_decimal4(assessment.threshold),
            status=assessment.status,
            signals_json=json.dumps(assessment.signals),
            reasons_json=json.dumps(assessment.reasons),
        )
        for assessment in evaluation.fields
    ]
    return run, fields


def _decimal4(value: float) -> Decimal:
    return Decimal(str(round(value, 4)))


def assess(
    provider: ExtractionProvider, data: bytes, config: WorkflowConfigModel
) -> tuple[ExtractionResult, DocumentTypeSpec, Evaluation]:
    """Extraction plus confidence scoring; runs under the worker's hard timeout."""
    result = provider.extract(data, config)
    type_spec = config.document_type(result.document_type) or config.document_types[0]
    return result, type_spec, evaluate(result.fields, result.pages, type_spec)


def complete(
    claim: Claim,
    result: ExtractionResult,
    evaluation: Evaluation,
    type_spec: DocumentTypeSpec,
    provider: ExtractionProvider,
    config: WorkflowConfigModel,
) -> None:
    now = datetime.now(UTC)
    with SessionLocal() as session, session.begin():
        set_org_context(session, claim.org_id)
        # Serialize completion with lease reclamation. Reading the lease without
        # a lock can let an old worker commit after another worker reclaims it.
        lease = _current_lease(session, claim)
        if lease is None:
            return
        event, document = lease
        # Scoring already ran outside this transaction (under the timeout), so no
        # slow check holds these row locks. The validating step is still recorded,
        # and a crash here rolls back to the leased "extracting" state.
        document.status = "validating"
        document.updated_at = now
        session.add(audit(claim.org_id, claim.document_id, "document.validating", None, now))
        session.flush()

        run, fields = _store_run(claim, result, provider, evaluation, now)
        session.add(run)
        session.flush()
        session.add_all(fields)
        flagged = [item.name for item in evaluation.fields if item.status == "needs_review"]
        failed_rules = [rule.name for rule in evaluation.rule_results if rule.passed is False]

        document.document_type = type_spec.name
        document.failure_reason = None
        event.published_at = now
        if config.review_policy == "always" or flagged or failed_rules:
            document.status = "needs_review"
            open_review_task(
                session, claim.org_id, claim.document_id, config.review_sla_minutes, now
            )
            session.add(
                audit(
                    claim.org_id,
                    claim.document_id,
                    "document.needs_review",
                    {"flagged_fields": flagged, "failed_rules": failed_rules},
                    now + timedelta(microseconds=1),
                )
            )
        else:
            document.status = "auto_approved"
            session.add(
                audit(
                    claim.org_id,
                    claim.document_id,
                    "document.auto_approved",
                    None,
                    now + timedelta(microseconds=1),
                )
            )


def fail(claim: Claim, reason: str, retryable: bool) -> None:
    now = datetime.now(UTC)
    with SessionLocal() as session, session.begin():
        set_org_context(session, claim.org_id)
        lease = _current_lease(session, claim)
        if lease is None:
            return
        event, document = lease
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
            session.add(
                audit(claim.org_id, claim.document_id, "document.failed", {"reason": reason[:200]})
            )


def process_one(
    store: ObjectStore | None = None, document_id: uuid.UUID | None = None
) -> bool:
    global _last_org_id
    object_store = store or get_store()
    provider = get_provider()
    with SessionLocal() as session:
        org_ids = list(session.scalars(select(Organization.id).order_by(Organization.id)))
    # Starting at the same tenant after every job can starve later tenants if
    # the first tenant has a continuous backlog. Rotate after each claim.
    if _last_org_id is not None and org_ids:
        pivot = bisect(org_ids, _last_org_id)
        org_ids = org_ids[pivot:] + org_ids[:pivot]
    for org_id in org_ids:
        claim = claim_next(org_id, document_id)
        if claim is None:
            continue
        _last_org_id = org_id
        if claim.attempts > MAX_EXTRACTION_ATTEMPTS:
            fail(
                claim,
                "Extraction attempt limit reached after worker interruption",
                retryable=False,
            )
            return True
        config = load_pinned_config(claim.org_id, claim.workflow_config_version)
        if config is None:
            fail(claim, "Workflow configuration version is missing", retryable=False)
            return True
        try:
            data = object_store.get(claim.storage_key)
            if (
                len(data) != claim.size_bytes
                or hashlib.sha256(data).hexdigest() != claim.content_hash
            ):
                fail(claim, "Stored document failed integrity check", retryable=False)
                return True
            # Parsing, extraction and scoring run under a hard wall-clock limit so
            # one hostile PDF or hung provider cannot hold the worker forever.
            result, type_spec, evaluation = run_with_timeout(
                partial(assess, provider, data, config),
                get_settings().extraction_timeout_seconds,
            )
        except ExtractionError as exc:
            fail(claim, str(exc), retryable=False)
        except OperationTimeout:
            fail(claim, "Extraction timed out", retryable=False)
        except ParserBusy:
            fail(claim, "Worker is at its parsing limit", retryable=True)
        except StoredDocumentTooLarge:
            fail(claim, "Stored document exceeds upload size limit", retryable=False)
        except (StorageError, ProviderUnavailable):
            fail(claim, "Storage or extraction provider was unavailable", retryable=True)
        except Exception:
            logger.exception("Unexpected extraction error for document %s", claim.document_id)
            fail(claim, "Extraction failed after retries", retryable=True)
        else:
            complete(claim, result, evaluation, type_spec, provider, config)
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
