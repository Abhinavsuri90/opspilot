"""Postgres outbox worker: extraction, action proposal and governed action execution.

Three topics share one claim/lease mechanism: ``extract_document`` (documents),
``propose_actions`` (after approval) and ``execute_action`` (one connector call per job).
"""

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
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app import actions_service
from app.action_models import Action
from app.actions_service import ExecutionPlan
from app.confidence import Evaluation, evaluate
from app.config import get_settings
from app.connectors import get_connector
from app.connectors.base import CredentialsUnavailable, ExecutionResult
from app.connectors.credentials import decrypt_credentials
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
from app.repositories import (
    get_action,
    get_document_by_id,
    get_outbox_event,
    get_workflow_config_version,
)
from app.review_service import open_review_task
from app.storage import ObjectStore, StorageError, StoredDocumentTooLarge, get_store
from app.timeouts import OperationTimeout, ParserBusy, run_connector_call, run_with_timeout
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


@dataclass(frozen=True)
class ActionClaim:
    org_id: uuid.UUID
    event_id: uuid.UUID
    document_id: uuid.UUID
    action_id: uuid.UUID | None
    topic: str
    claimed_at: datetime
    attempts: int


ACTION_TOPICS = ("propose_actions", "execute_action")
# An action job that has been claimed this many consecutive times without recording an
# outcome (a worker crash loop) is abandoned; deliberate hand-backs reset the count.
MAX_ACTION_EVENT_ATTEMPTS = 3
# Recording the outcome after a successful external call is the double-execution path, so
# a transient database error there is retried briefly instead of leaving the job to replay.
FINISH_RETRY_ATTEMPTS = 3
FINISH_RETRY_DELAY_SECONDS = 0.5


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


def claim_action_event(
    org_id: uuid.UUID, topic: str, document_id: uuid.UUID | None = None
) -> ActionClaim | None:
    """Lease the next propose/execute job for one tenant; stale leases are reclaimed."""
    now = datetime.now(UTC)
    stale_before = now - timedelta(seconds=stale_lease_seconds())
    with SessionLocal() as session, session.begin():
        set_org_context(session, org_id)
        statement = (
            select(OutboxEvent)
            .where(
                OutboxEvent.org_id == org_id,
                OutboxEvent.topic == topic,
                OutboxEvent.published_at.is_(None),
                OutboxEvent.available_at <= now,
                or_(OutboxEvent.claimed_at.is_(None), OutboxEvent.claimed_at < stale_before),
            )
            .order_by(OutboxEvent.created_at, OutboxEvent.id)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if document_id is not None:
            statement = statement.where(OutboxEvent.document_id == document_id)
        if topic == "execute_action":
            statement = statement.join(Action, Action.id == OutboxEvent.action_id).where(
                Action.org_id == org_id,
                Action.status.in_(("approved", "retrying", "executing")),
                or_(Action.next_attempt_at.is_(None), Action.next_attempt_at <= now),
            )
        event = session.scalar(statement)
        if event is None:
            return None
        event.claimed_at = now
        event.attempts += 1
        return ActionClaim(
            org_id, event.id, event.document_id, event.action_id, topic, now, event.attempts
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
            # Approval without a human still goes through the action governance path.
            actions_service.enqueue_propose_actions(session, claim.org_id, claim.document_id, now)


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
            for topic in ACTION_TOPICS:
                action_claim = claim_action_event(org_id, topic, document_id)
                if action_claim is not None:
                    _last_org_id = org_id
                    handle_action_claim(action_claim)
                    return True
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


def handle_action_claim(claim: ActionClaim) -> None:
    if claim.attempts > MAX_ACTION_EVENT_ATTEMPTS:
        abandon_event(claim)
    elif claim.topic == "propose_actions":
        propose_actions(claim)
    else:
        execute_action(claim)


def _leased_event(session: Session, claim: ActionClaim) -> OutboxEvent | None:
    event = get_outbox_event(session, claim.org_id, claim.event_id, lock=True)
    if event is None or event.claimed_at != claim.claimed_at or event.published_at is not None:
        return None
    return event


def abandon_event(claim: ActionClaim) -> None:
    """Publish a job that keeps interrupting the worker and fail its action, if any."""
    now = datetime.now(UTC)
    with SessionLocal() as session, session.begin():
        set_org_context(session, claim.org_id)
        event = _leased_event(session, claim)
        if event is None:
            return
        action = (
            get_action(session, claim.org_id, claim.action_id, lock=True)
            if claim.action_id is not None
            else None
        )
        document = get_document_by_id(session, claim.org_id, claim.document_id)
        actions_service.abandon_event(session, event, action, document, now)
        logger.warning(
            "Abandoned %s event %s after %d claims", claim.topic, claim.event_id, claim.attempts
        )


def propose_actions(claim: ActionClaim) -> None:
    """Turn an approved document into governed actions; no external call happens here."""
    now = datetime.now(UTC)
    with SessionLocal() as session, session.begin():
        set_org_context(session, claim.org_id)
        event = _leased_event(session, claim)
        if event is None:
            return
        document = get_document_by_id(session, claim.org_id, claim.document_id, lock=True)
        event.published_at = now
        if document is None or document.status not in {
            "approved",
            "auto_approved",
            "actions_pending",
        }:
            return
        config = load_pinned_config(claim.org_id, document.workflow_config_version)
        if config is None:
            logger.warning("Document %s has no loadable workflow config", document.id)
            return
        outcome = actions_service.propose_for_document(session, document, config, now)
        logger.info(
            "Proposed %d action(s) for document %s (%d duplicate(s) skipped)",
            len(outcome.created),
            document.id,
            outcome.skipped,
        )


def execute_action(claim: ActionClaim) -> None:
    """Gate, then call the connector outside any transaction, then record the outcome."""
    if claim.action_id is None:
        return
    now = datetime.now(UTC)
    plan: ExecutionPlan | None = None
    with SessionLocal() as session, session.begin():
        set_org_context(session, claim.org_id)
        event = _leased_event(session, claim)
        if event is None:
            return
        action = get_action(session, claim.org_id, claim.action_id, lock=True)
        document = get_document_by_id(session, claim.org_id, claim.document_id)
        if action is None or document is None:
            event.published_at = now
            return
        if action.status not in {"approved", "retrying", "executing"}:
            event.published_at = now
            return
        config = load_pinned_config(claim.org_id, document.workflow_config_version)
        if config is None:
            actions_service.settle(
                session, action, event, document, "failed", now, error="workflow config missing"
            )
            return
        # The policy and kill-switch check happens here, in the transaction that marks the
        # action executing, immediately before the external call.
        decision = actions_service.gate(session, action, config)
        if decision == "kill_switch":
            actions_service.block_for_kill_switch(session, action, event, now)
            logger.info("Kill switch blocked action %s", action.id)
            return
        if decision == "forbidden":
            actions_service.settle(session, action, event, document, "forbidden", now)
            return
        if decision == "needs_approval":
            actions_service.require_approval(session, action, event, document, now)
            logger.info("Action %s now needs human approval", action.id)
            return
        if decision == "shadow":
            actions_service.settle(
                session,
                action,
                event,
                document,
                "shadowed",
                now,
                result=json.loads(action.preview_json),
            )
            return
        connector_row = actions_service.resolve_connector(session, action, config)
        if connector_row is None or not connector_row.active:
            actions_service.settle(
                session, action, event, document, "failed", now, error="connector missing"
            )
            return
        if action.attempts >= actions_service.MAX_ACTION_ATTEMPTS:
            actions_service.settle(
                session,
                action,
                event,
                document,
                "dead_lettered",
                now,
                error="Attempt budget exhausted after worker interruption",
            )
            return
        plan = actions_service.start_attempt(session, action, connector_row, now)
    started = datetime.now(UTC)
    try:
        result = run_connector(plan)
    except ParserBusy:
        defer_attempt(claim, plan)
        return
    finished = datetime.now(UTC)
    for remaining in range(FINISH_RETRY_ATTEMPTS - 1, -1, -1):
        try:
            record_outcome(claim, result, started, finished)
            return
        except OperationalError:
            if remaining == 0:
                raise
            logger.warning(
                "Recording action %s outcome hit a transient database error; retrying",
                claim.action_id,
            )
            time.sleep(FINISH_RETRY_DELAY_SECONDS)


def defer_attempt(claim: ActionClaim, plan: ExecutionPlan) -> None:
    """Every connector slot is busy: hand the job back untouched for a short retry."""
    now = datetime.now(UTC)
    with SessionLocal() as session, session.begin():
        set_org_context(session, claim.org_id)
        event = _leased_event(session, claim)
        action = (
            get_action(session, claim.org_id, claim.action_id, lock=True)
            if claim.action_id is not None
            else None
        )
        if event is None or action is None or action.status != "executing":
            return
        actions_service.defer_attempt(session, action, event, plan, now)
        logger.info("Deferred action %s: worker at its connector-call limit", action.id)


def record_outcome(
    claim: ActionClaim, result: ExecutionResult, started: datetime, finished: datetime
) -> None:
    if claim.action_id is None:
        return
    with SessionLocal() as session, session.begin():
        set_org_context(session, claim.org_id)
        event = _leased_event(session, claim)
        if event is None:
            return
        action = get_action(session, claim.org_id, claim.action_id, lock=True)
        document = get_document_by_id(session, claim.org_id, claim.document_id)
        if action is None or document is None or action.status != "executing":
            return
        actions_service.finish_attempt(session, action, event, document, result, started, finished)
        logger.info(
            "Action %s attempt %d finished with status %s",
            action.id,
            action.attempts,
            action.status,
        )


def run_connector(plan: ExecutionPlan) -> ExecutionResult:
    """The only place an external side effect happens; bounded by a hard timeout.

    Raises :class:`ParserBusy` when every connector slot is taken, before anything ran.
    """
    try:
        credentials = (
            decrypt_credentials(plan.credentials_encrypted) if plan.credentials_encrypted else None
        )
        connector = get_connector(plan.connector_type)
        return run_connector_call(
            partial(
                connector.execute, plan.config, credentials, plan.request, plan.idempotency_key
            ),
            get_settings().action_execute_timeout_seconds,
        )
    except ParserBusy:
        raise
    except CredentialsUnavailable as exc:
        return ExecutionResult(False, None, str(exc), retryable=False)
    except OperationTimeout:
        return ExecutionResult(False, None, "Connector call timed out", retryable=True)
    except Exception as exc:
        logger.exception(
            "Connector %s raised for action %s", plan.connector_type, plan.request.action_id
        )
        return ExecutionResult(
            False, None, f"Connector raised {type(exc).__name__}", retryable=True
        )


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
