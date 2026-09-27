"""Governed actions: proposal, human decision, the pre-execution gate and attempt bookkeeping.

Every external side effect is an ``actions`` row. The worker re-reads the organization's
kill switch and the action's policy in the same transaction that marks the action
``executing``, immediately before the connector call, so a switch flipped after approval
still stops execution. Design notes: docs/adr/007-governed-actions.md.
"""

import hashlib
import json
import logging
import random
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.action_models import (
    OPEN_ACTION_STATUSES,
    Action,
    ActionAttempt,
    ConnectorInstance,
)
from app.connectors import connector_type_for, get_connector
from app.connectors.base import ActionRequest, Diff, ExecutionResult
from app.document_service import document_audit
from app.models import AuditEvent, Document, OutboxEvent
from app.repositories import (
    ensure_org_settings,
    get_accessible_action,
    get_action,
    get_action_by_idempotency_key,
    get_action_policy,
    get_connector_by_name,
    get_connector_instance,
    get_document_by_id,
    get_org_settings,
    list_action_attempts,
    list_connector_actions,
    list_document_actions,
)
from app.review_service import effective_fields
from app.workflow_config import DestinationSpec, WorkflowConfigModel
from app.workflow_models import InvoiceCategory, InvoiceMetadata

logger = logging.getLogger(__name__)
MAX_ACTION_ATTEMPTS = 5
KILL_SWITCH_RECHECK_SECONDS = 60
KILL_SWITCH_AUDIT_INTERVAL = timedelta(hours=1)
# A worker at its connector-call cap defers the attempt instead of spending budget on it.
BUSY_RETRY_SECONDS = 30
DECIDER_ROLES = frozenset({"admin", "reviewer"})
Decision = Literal["approve", "reject"]
Gate = Literal["execute", "kill_switch", "forbidden", "shadow", "needs_approval"]


class ActionNotFound(Exception):
    pass


class ActionForbidden(Exception):
    pass


class ActionConflict(Exception):
    pass


class DiffResponse(BaseModel):
    kind: str
    title: str
    before: dict[str, Any] | None
    after: dict[str, Any]
    lines: list[str]


class AttemptResponse(BaseModel):
    attempt: int
    started_at: datetime
    finished_at: datetime
    ok: bool
    response_summary: str | None
    error: str | None


class ActionSummary(BaseModel):
    id: uuid.UUID
    document_id: uuid.UUID
    filename: str
    destination: str
    action_type: str
    connector_id: uuid.UUID | None
    connector_name: str | None
    status: str
    policy_mode: str
    preview: DiffResponse
    attempts: int
    next_attempt_at: datetime | None
    error: str | None
    proposed_at: datetime
    decided_by_email: str | None
    decided_at: datetime | None
    decision_comment: str
    executed_at: datetime | None
    version: int


class ActionDetail(ActionSummary):
    payload: dict[str, str]
    result: dict[str, Any] | None
    attempt_log: list[AttemptResponse]


@dataclass(frozen=True)
class ExecutionPlan:
    """Everything the worker needs for the connector call, captured inside the gate."""

    connector_type: str
    config: dict[str, Any]
    credentials_encrypted: str | None
    request: ActionRequest
    idempotency_key: str
    attempt: int
    # Status before the attempt started, restored when the worker could not even begin it.
    previous_status: str


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _load_dict(raw: str | None) -> dict[str, Any]:
    try:
        decoded = json.loads(raw or "{}")
    except ValueError:
        return {}
    return dict(decoded) if isinstance(decoded, dict) else {}


def load_preview(raw: str) -> DiffResponse:
    decoded = _load_dict(raw)
    after = decoded.get("after")
    before = decoded.get("before")
    lines = decoded.get("lines")
    return DiffResponse(
        kind=str(decoded.get("kind", "")),
        title=str(decoded.get("title", "")),
        before=dict(before) if isinstance(before, dict) else None,
        after=dict(after) if isinstance(after, dict) else {},
        lines=[str(line) for line in lines] if isinstance(lines, list) else [],
    )


def load_payload(raw: str) -> dict[str, str]:
    return {str(key): str(value) for key, value in _load_dict(raw).items()}


def summarize(
    action: Action, document: Document, connector_name: str | None, decider_email: str | None
) -> ActionSummary:
    return ActionSummary(
        id=action.id,
        document_id=action.document_id,
        filename=document.filename,
        destination=action.destination,
        action_type=action.action_type,
        connector_id=action.connector_id,
        connector_name=connector_name,
        status=action.status,
        policy_mode=action.policy_mode,
        preview=load_preview(action.preview_json),
        attempts=action.attempts,
        next_attempt_at=action.next_attempt_at,
        error=action.error,
        proposed_at=action.proposed_at,
        decided_by_email=decider_email,
        decided_at=action.decided_at,
        decision_comment=action.decision_comment,
        executed_at=action.executed_at,
        version=action.version,
    )


def detail(
    session: Session,
    action: Action,
    document: Document,
    connector_name: str | None,
    decider_email: str | None,
) -> ActionDetail:
    result = _load_dict(action.result_json) if action.result_json else None
    return ActionDetail(
        **summarize(action, document, connector_name, decider_email).model_dump(),
        payload=load_payload(action.payload_json),
        result=result,
        attempt_log=[
            AttemptResponse(
                attempt=row.attempt,
                started_at=row.started_at,
                finished_at=row.finished_at,
                ok=row.ok,
                response_summary=row.response_summary,
                error=row.error,
            )
            for row in list_action_attempts(session, action.org_id, action.id)
        ],
    )


def read_action(
    session: Session, org_id: uuid.UUID, user_id: uuid.UUID, role: str, action_id: uuid.UUID
) -> ActionDetail | None:
    row = get_accessible_action(session, org_id, user_id, role, action_id)
    if row is None:
        return None
    action, document, connector_name, decider_email = row
    return detail(session, action, document, connector_name, decider_email)


# Outbox


def enqueue_propose_actions(
    session: Session, org_id: uuid.UUID, document_id: uuid.UUID, now: datetime | None = None
) -> OutboxEvent:
    event = OutboxEvent(
        id=uuid.uuid4(),
        org_id=org_id,
        document_id=document_id,
        topic="propose_actions",
        payload_json=json.dumps({"document_id": str(document_id)}),
        attempts=0,
        available_at=now or datetime.now(UTC),
    )
    session.add(event)
    return event


def enqueue_execute_action(
    session: Session, action: Action, now: datetime | None = None
) -> OutboxEvent:
    event = OutboxEvent(
        id=uuid.uuid4(),
        org_id=action.org_id,
        document_id=action.document_id,
        action_id=action.id,
        topic="execute_action",
        payload_json=json.dumps({"action_id": str(action.id)}),
        attempts=0,
        available_at=now or datetime.now(UTC),
    )
    session.add(event)
    return event


# Proposal


def idempotency_key(
    org_id: uuid.UUID,
    document_id: uuid.UUID,
    destination: str,
    action_type: str,
    values: dict[str, str],
) -> str:
    canonical = json.dumps(
        [str(org_id), str(document_id), destination, action_type, values],
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:64]


def build_values(
    session: Session, document: Document, destination: DestinationSpec
) -> dict[str, str]:
    """Resolve a destination mapping against the document's effective fields and metadata."""
    org_id = document.org_id
    fields = {
        item.field.name: item.current_value
        for item in effective_fields(session, org_id, document.id)
    }
    metadata = session.scalar(
        select(InvoiceMetadata).where(
            InvoiceMetadata.org_id == org_id, InvoiceMetadata.document_id == document.id
        )
    )
    category = ""
    if metadata is not None and metadata.category_id is not None:
        row = session.scalar(
            select(InvoiceCategory).where(
                InvoiceCategory.org_id == org_id, InvoiceCategory.id == metadata.category_id
            )
        )
        category = row.name if row is not None else ""
    literals = {
        "${document.id}": str(document.id),
        "${document.filename}": document.filename,
        "${document.document_type}": document.document_type,
        "${verified.amount}": (
            str(metadata.verified_amount)
            if metadata is not None and metadata.verified_amount is not None
            else ""
        ),
        "${verified.currency}": (metadata.currency or "") if metadata is not None else "",
        "${category.name}": category,
    }
    return {
        column: literals[source] if source in literals else fields.get(source, "")
        for column, source in destination.mapping.items()
    }


def effective_policy(
    session: Session, org_id: uuid.UUID, config: WorkflowConfigModel, action_type: str
) -> str:
    row = get_action_policy(session, org_id, action_type)
    if row is not None:
        return row.mode
    return config.action_policies.get(action_type, "needs_approval")


def action_request(action: Action, connector_id: uuid.UUID) -> ActionRequest:
    return ActionRequest(
        org_id=action.org_id,
        connector_id=connector_id,
        action_id=action.id,
        document_id=action.document_id,
        action_type=action.action_type,
        values=load_payload(action.payload_json),
        proposed_at=_aware(action.proposed_at),
    )


def _generic_preview(
    action_type: str, destination: DestinationSpec, values: dict[str, str]
) -> Diff:
    return Diff(
        kind=action_type,
        title=f"{action_type} via {destination.connector}",
        before=None,
        after=dict(values),
        lines=[f"{column}: {value}" for column, value in values.items()],
    )


def _audit_action(
    action: Action,
    event_type: str,
    detail_payload: dict[str, object] | None = None,
    actor: uuid.UUID | None = None,
    created_at: datetime | None = None,
) -> AuditEvent:
    return document_audit(
        action.org_id,
        action.document_id,
        actor,
        event_type,
        {
            "action_id": str(action.id),
            "destination": action.destination,
            "action_type": action.action_type,
            "status": action.status,
            **(detail_payload or {}),
        },
        created_at,
    )


@dataclass
class ProposalOutcome:
    created: list[Action]
    skipped: int = 0


def propose_for_document(
    session: Session, document: Document, config: WorkflowConfigModel, now: datetime
) -> ProposalOutcome:
    """Create one action per enabled destination; identical proposals are deduplicated."""
    outcome = ProposalOutcome(created=[])
    order = 0
    for destination in config.destinations_for(document.document_type):
        values = build_values(session, document, destination)
        key = idempotency_key(
            document.org_id, document.id, destination.name, destination.action_type, values
        )
        if get_action_by_idempotency_key(session, document.org_id, key) is not None:
            outcome.skipped += 1
            continue
        connector_row = get_connector_by_name(session, document.org_id, destination.connector)
        policy = effective_policy(session, document.org_id, config, destination.action_type)
        stamp = now + timedelta(microseconds=order)
        order += 1
        action = Action(
            id=uuid.uuid4(),
            org_id=document.org_id,
            document_id=document.id,
            connector_id=None,
            action_type=destination.action_type,
            destination=destination.name,
            payload_json=json.dumps(values, sort_keys=True),
            preview_json="{}",
            status="proposed",
            policy_mode=policy,
            idempotency_key=key,
            attempts=0,
            proposed_at=stamp,
            version=0,
        )
        preview = _generic_preview(destination.action_type, destination, values)
        error = _connector_problem(connector_row, destination.action_type)
        if error is None and connector_row is not None:
            action.connector_id = connector_row.id
            try:
                preview = get_connector(connector_row.connector_type).preview(
                    _load_dict(connector_row.config_json), action_request(action, connector_row.id)
                )
            except Exception:
                logger.exception(
                    "Preview failed for destination %s of document %s",
                    destination.name,
                    document.id,
                )
                error = "preview failed"
        action.preview_json = json.dumps(preview.as_dict(), default=str)
        session.add(action)
        session.flush()
        if error is not None:
            action.status = "failed"
            action.error = error
            session.add(_audit_action(action, "action.proposed", {"error": error}, None, stamp))
            session.add(
                _audit_action(
                    action,
                    "action.failed",
                    {"error": error},
                    None,
                    stamp + timedelta(microseconds=1),
                )
            )
        elif policy == "forbidden":
            action.status = "forbidden"
            session.add(_audit_action(action, "action.proposed", None, None, stamp))
            session.add(
                _audit_action(
                    action, "action.forbidden", None, None, stamp + timedelta(microseconds=1)
                )
            )
        elif policy == "auto":
            action.status = "approved"
            enqueue_execute_action(session, action, now)
            session.add(_audit_action(action, "action.proposed", None, None, stamp))
        else:
            session.add(_audit_action(action, "action.proposed", None, None, stamp))
        outcome.created.append(action)
    recompute_document_status(session, document, now + timedelta(microseconds=order))
    return outcome


def _connector_problem(connector_row: ConnectorInstance | None, action_type: str) -> str | None:
    if connector_row is None:
        return "connector missing"
    if not connector_row.active:
        return "connector inactive"
    expected = connector_type_for(action_type)
    if expected is not None and connector_row.connector_type != expected:
        return f"connector type mismatch: {action_type} needs a {expected} connector"
    return None


def recompute_document_status(session: Session, document: Document, now: datetime) -> None:
    """A document is actions_pending while any action still needs a worker or a human."""
    if document.status not in {"approved", "auto_approved", "actions_pending", "completed"}:
        return
    statuses = {
        action.status for action in list_document_actions(session, document.org_id, document.id)
    }
    target = "actions_pending" if statuses & OPEN_ACTION_STATUSES else "completed"
    if document.status == target:
        return
    document.status = target
    document.updated_at = now
    session.add(document_audit(document.org_id, document.id, None, f"document.{target}", None, now))


# Human decisions


def _decidable(
    session: Session, org_id: uuid.UUID, user_id: uuid.UUID, role: str, action_id: uuid.UUID
) -> tuple[Action, Document]:
    row = get_accessible_action(session, org_id, user_id, role, action_id)
    if row is None:
        raise ActionNotFound("Action not found")
    if role not in DECIDER_ROLES:
        raise ActionForbidden("Only a reviewer or administrator can decide actions")
    action = get_action(session, org_id, action_id, lock=True)
    document = get_document_by_id(session, org_id, row[1].id)
    if action is None or document is None:
        raise ActionNotFound("Action not found")
    return action, document


def decide_action(
    session: Session,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    role: str,
    action_id: uuid.UUID,
    decision: Decision,
    comment: str,
    version: int,
    now: datetime | None = None,
) -> Action:
    now = now or datetime.now(UTC)
    action, document = _decidable(session, org_id, user_id, role, action_id)
    if action.version != version:
        raise ActionConflict("Action changed. Refresh it before deciding again.")
    if action.status != "proposed":
        raise ActionConflict("Only proposed actions can be approved or rejected")
    action.status = "approved" if decision == "approve" else "rejected"
    action.decided_by = user_id
    action.decided_at = now
    action.decision_comment = comment
    action.version += 1
    if decision == "approve":
        action.next_attempt_at = None
        enqueue_execute_action(session, action, now)
    session.add(
        _audit_action(action, f"action.{action.status}", {"comment": comment}, user_id, now)
    )
    recompute_document_status(session, document, now + timedelta(microseconds=1))
    session.flush()
    return action


def retry_action(
    session: Session,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    role: str,
    action_id: uuid.UUID,
    version: int,
    now: datetime | None = None,
) -> Action:
    now = now or datetime.now(UTC)
    action, document = _decidable(session, org_id, user_id, role, action_id)
    if action.version != version:
        raise ActionConflict("Action changed. Refresh it before retrying.")
    if action.status not in {"dead_lettered", "failed"}:
        raise ActionConflict("Only failed or dead-lettered actions can be retried")
    previous = action.status
    action.status = "approved"
    action.attempts = 0
    action.next_attempt_at = None
    action.claimed_at = None
    action.error = None
    action.version += 1
    enqueue_execute_action(session, action, now)
    session.add(_audit_action(action, "action.retried", {"from_status": previous}, user_id, now))
    recompute_document_status(session, document, now + timedelta(microseconds=1))
    session.flush()
    return action


def _undecided(action: Action) -> bool:
    """Approved automatically and not started: no human has looked at it yet."""
    return action.status == "approved" and action.decided_by is None and action.attempts == 0


def _withdrawable_on_reopen(action: Action) -> bool:
    return action.status in {"proposed", "retrying", "dead_lettered"} or _undecided(action)


def _reject(action: Action, user_id: uuid.UUID, now: datetime, reason: str) -> AuditEvent:
    previous = action.status
    action.status = "rejected"
    action.decided_by = user_id
    action.decided_at = now
    action.decision_comment = reason
    action.next_attempt_at = None
    action.version += 1
    return _audit_action(
        action,
        "action.rejected",
        {"withdrawn": True, "reason": reason, "from_status": previous},
        user_id,
        now,
    )


def withdraw_open_actions(
    session: Session, document: Document, user_id: uuid.UUID, now: datetime
) -> int:
    """Reject actions built from values that are about to be reviewed again.

    Proposed, retrying and dead-lettered actions, and auto-approved ones that have not
    started, are superseded. An action a worker is executing right now is left alone; the
    row lock makes that decision atomic with the worker's own transition.
    """
    withdrawn = 0
    for action in list_document_actions(session, document.org_id, document.id, lock=True):
        if not _withdrawable_on_reopen(action):
            continue
        session.add(_reject(action, user_id, now, "Superseded: document reopened"))
        withdrawn += 1
    return withdrawn


def supersede_connector_actions(
    session: Session, org_id: uuid.UUID, connector_id: uuid.UUID, user_id: uuid.UUID, now: datetime
) -> int:
    """A changed connector configuration invalidates previews nobody has approved yet."""
    superseded = 0
    touched: dict[uuid.UUID, Document] = {}
    for action in list_connector_actions(session, org_id, connector_id, ("proposed", "approved")):
        if action.status == "approved" and not _undecided(action):
            continue
        session.add(_reject(action, user_id, now, "Superseded: connector changed"))
        superseded += 1
        if action.document_id not in touched:
            document = get_document_by_id(session, org_id, action.document_id)
            if document is not None:
                touched[action.document_id] = document
    for document in touched.values():
        recompute_document_status(session, document, now + timedelta(microseconds=1))
    return superseded


# Worker-side gate and bookkeeping


def resolve_connector(
    session: Session, action: Action, config: WorkflowConfigModel
) -> ConnectorInstance | None:
    """The action's connector; a retried "connector missing" action is re-resolved by name."""
    if action.connector_id is None:
        destination = next((d for d in config.destinations if d.name == action.destination), None)
        if destination is None:
            return None
        row = get_connector_by_name(session, action.org_id, destination.connector)
        if row is None or _connector_problem(row, action.action_type) is not None:
            return None
        action.connector_id = row.id
        return row
    return get_connector_instance(session, action.org_id, action.connector_id)


def gate(session: Session, action: Action, config: WorkflowConfigModel) -> Gate:
    """Re-read the organization switches and policy immediately before execution.

    FOR SHARE on the settings row means an administrator flipping the kill switch either
    commits before this read (and blocks the run) or waits until this transaction ends.
    """
    settings = get_org_settings(session, action.org_id, lock="share")
    if settings is None:
        ensure_org_settings(session, action.org_id)
        settings = get_org_settings(session, action.org_id, lock="share")
    kill_switch = bool(settings.kill_switch) if settings is not None else False
    shadow = bool(settings.shadow_mode) if settings is not None else False
    if kill_switch:
        return "kill_switch"
    policy_row = get_action_policy(session, action.org_id, action.action_type, lock=True)
    mode = (
        policy_row.mode
        if policy_row is not None
        else config.action_policies.get(action.action_type, action.policy_mode)
    )
    if mode == "forbidden":
        return "forbidden"
    if mode == "needs_approval" and action.decided_by is None:
        # The policy was tightened after an automatic approval: a human must decide first.
        return "needs_approval"
    if shadow:
        return "shadow"
    return "execute"


def require_approval(
    session: Session, action: Action, event: OutboxEvent, document: Document, now: datetime
) -> None:
    """Send an auto-approved action back to the queue because the policy now needs a human."""
    action.status = "proposed"
    action.policy_mode = "needs_approval"
    action.claimed_at = None
    action.next_attempt_at = None
    action.version += 1
    event.published_at = now
    session.add(_audit_action(action, "action.needs_approval", None, None, now))
    recompute_document_status(session, document, now + timedelta(microseconds=1))


def defer_attempt(
    session: Session, action: Action, event: OutboxEvent, plan: ExecutionPlan, now: datetime
) -> None:
    """The worker could not start the connector call; give the slot back without cost."""
    retry_at = now + timedelta(seconds=BUSY_RETRY_SECONDS)
    action.status = plan.previous_status
    action.attempts = max(0, action.attempts - 1)
    action.claimed_at = None
    action.next_attempt_at = retry_at
    action.version += 1
    event.available_at = retry_at
    event.claimed_at = None
    event.attempts = 0


def abandon_event(
    session: Session,
    event: OutboxEvent,
    action: Action | None,
    document: Document | None,
    now: datetime,
) -> None:
    """A job that keeps interrupting the worker is published so it cannot poison the queue."""
    event.published_at = now
    session.add(
        document_audit(
            event.org_id,
            event.document_id,
            None,
            "action.event_abandoned",
            {
                "topic": event.topic,
                "event_id": str(event.id),
                "attempts": event.attempts,
                "action_id": str(action.id) if action is not None else None,
            },
            now,
        )
    )
    if (
        action is not None
        and document is not None
        and action.status
        in {
            "approved",
            "retrying",
            "executing",
        }
    ):
        settle(
            session,
            action,
            event,
            document,
            "failed",
            now + timedelta(microseconds=1),
            error="worker interrupted repeatedly",
        )


def block_for_kill_switch(
    session: Session, action: Action, event: OutboxEvent, now: datetime
) -> None:
    retry_at = now + timedelta(seconds=KILL_SWITCH_RECHECK_SECONDS)
    action.next_attempt_at = retry_at
    action.claimed_at = None
    event.available_at = retry_at
    event.claimed_at = None
    # A deliberate hand-back is not an interruption: the poison-event cap counts only
    # consecutive claims that never recorded an outcome.
    event.attempts = 0
    if _should_audit_block(session, action, now):
        session.add(
            _audit_action(
                action,
                "action.blocked_kill_switch",
                {"attempts": action.attempts, "retry_at": retry_at.isoformat()},
                None,
                now,
            )
        )


def _should_audit_block(session: Session, action: Action, now: datetime) -> bool:
    last = session.scalar(
        select(AuditEvent)
        .where(
            AuditEvent.org_id == action.org_id,
            AuditEvent.document_id == action.document_id,
            AuditEvent.event_type == "action.blocked_kill_switch",
            AuditEvent.detail_json.contains(str(action.id)),
        )
        .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
        .limit(1)
    )
    if last is None:
        return True
    if _aware(last.created_at) < now - KILL_SWITCH_AUDIT_INTERVAL:
        return True
    return _load_dict(last.detail_json).get("attempts") != action.attempts


def settle(
    session: Session,
    action: Action,
    event: OutboxEvent,
    document: Document,
    status: Literal["forbidden", "shadowed", "failed", "dead_lettered"],
    now: datetime,
    *,
    error: str | None = None,
    result: dict[str, Any] | None = None,
) -> None:
    """Terminal transition made without calling the connector."""
    action.status = status
    action.error = error[:500] if error else None
    action.claimed_at = None
    action.next_attempt_at = None
    action.version += 1
    if result is not None:
        action.result_json = json.dumps(result, default=str)
    if status == "shadowed":
        action.executed_at = now
    event.published_at = now
    session.add(
        _audit_action(action, f"action.{status}", {"error": error} if error else None, None, now)
    )
    recompute_document_status(session, document, now + timedelta(microseconds=1))


def start_attempt(
    session: Session, action: Action, connector_row: ConnectorInstance, now: datetime
) -> ExecutionPlan:
    previous_status = action.status
    action.status = "executing"
    action.attempts += 1
    action.claimed_at = now
    action.next_attempt_at = None
    action.version += 1
    return ExecutionPlan(
        connector_type=connector_row.connector_type,
        config=_load_dict(connector_row.config_json),
        credentials_encrypted=connector_row.credentials_encrypted,
        request=action_request(action, connector_row.id),
        idempotency_key=action.idempotency_key,
        attempt=action.attempts,
        previous_status=previous_status,
    )


def backoff_seconds(attempts: int) -> float:
    """Exponential backoff in minutes (2, 4, 8, 16) with plus or minus 20 percent jitter."""
    return 60.0 * (2.0**attempts) * random.uniform(0.8, 1.2)


def finish_attempt(
    session: Session,
    action: Action,
    event: OutboxEvent,
    document: Document,
    result: ExecutionResult,
    started_at: datetime,
    now: datetime,
) -> None:
    session.add(
        ActionAttempt(
            id=uuid.uuid4(),
            org_id=action.org_id,
            action_id=action.id,
            attempt=action.attempts,
            started_at=started_at,
            finished_at=now,
            ok=result.ok,
            response_summary=result.response_summary[:500] if result.ok else None,
            error=None if result.ok else result.response_summary[:500],
        )
    )
    action.claimed_at = None
    action.version += 1
    if result.ok:
        action.status = "succeeded"
        action.error = None
        action.next_attempt_at = None
        action.executed_at = now
        action.result_json = json.dumps(
            {
                "external_id": result.external_id,
                "response_summary": result.response_summary,
                "duplicate": result.duplicate,
                "attempt": action.attempts,
            }
        )
        event.published_at = now
        session.add(
            _audit_action(action, "action.succeeded", {"attempt": action.attempts}, None, now)
        )
    elif result.retryable and action.attempts < MAX_ACTION_ATTEMPTS:
        action.status = "retrying"
        action.error = result.response_summary[:500]
        retry_at = now + timedelta(seconds=backoff_seconds(action.attempts))
        action.next_attempt_at = retry_at
        event.available_at = retry_at
        event.claimed_at = None
        event.attempts = 0  # an outcome was recorded; only unfinished claims count
        session.add(
            _audit_action(
                action,
                "action.retry_scheduled",
                {"attempt": action.attempts, "retry_at": retry_at.isoformat()},
                None,
                now,
            )
        )
    else:
        action.status = "dead_lettered" if result.retryable else "failed"
        action.error = result.response_summary[:500]
        action.next_attempt_at = None
        event.published_at = now
        session.add(
            _audit_action(
                action,
                f"action.{action.status}",
                {"attempt": action.attempts, "error": action.error},
                None,
                now,
            )
        )
    recompute_document_status(session, document, now + timedelta(microseconds=1))
