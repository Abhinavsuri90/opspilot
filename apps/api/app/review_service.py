"""Review queue, field corrections, effective values and the per-document timeline.

Extraction evidence is immutable. A reviewer's accept or edit is an append-only
``field_corrections`` row, and every reader derives the current value and status
from the latest correction through :func:`effective_fields`.
"""

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal, cast

from pydantic import BaseModel
from sqlalchemy import ScalarSelect, and_, func, select
from sqlalchemy.orm import Session, aliased

from app.access import accessible_document_clause, can_access_document
from app.confidence import evaluate_rules, format_problem, parse_money, typed_value
from app.document_service import DocumentSummary, summary
from app.models import AuditEvent, Document, ExtractedField, User
from app.repositories import (
    flagged_counts,
    get_document_by_id,
    get_extracted_field,
    get_review_task,
    get_workflow_config_version,
    latest_extraction_run,
    list_document_audit_events,
    list_document_comments,
    list_document_fields,
    list_document_reviews,
    list_extraction_runs,
    list_field_corrections,
)
from app.workflow_config import (
    DocumentTypeSpec,
    FieldSpec,
    WorkflowConfigModel,
    default_invoice_config,
    load_config,
)
from app.workflow_models import FieldCorrection, InvoiceMetadata, ReviewTask

FieldStatus = Literal["auto", "needs_review", "corrected", "approved"]
TimelineKind = Literal["audit", "extraction", "correction", "review", "comment"]
AssignedFilter = Literal["me", "unassigned", "all"]


class FieldNotFound(Exception):
    pass


class InvalidCorrection(Exception):
    pass


class FieldDetail(BaseModel):
    id: uuid.UUID
    name: str
    label: str
    field_type: str
    required: bool
    value: str
    current_value: str
    evidence: str
    page_number: int
    confidence: float
    threshold: float
    status: FieldStatus
    signals: dict[str, float | None]
    reasons: list[str]
    corrected_by_email: str | None


class RuleResultResponse(BaseModel):
    name: str
    expression: str
    passed: bool | None
    message: str


class ReviewTaskResponse(BaseModel):
    opened_at: datetime
    due_at: datetime
    sla_minutes: int
    completed_at: datetime | None
    outcome: str | None
    overdue: bool


class DocumentDetail(DocumentSummary):
    provider: str | None
    version: int
    fields: list[FieldDetail]
    rule_results: list[RuleResultResponse]
    review_task: ReviewTaskResponse | None


class QueueItem(BaseModel):
    document_id: uuid.UUID
    filename: str
    document_type: str
    vendor: str | None
    total: str | None
    currency: str | None
    flagged_count: int
    opened_at: datetime | None
    due_at: datetime | None
    overdue: bool
    assigned_reviewer_id: uuid.UUID | None
    assigned_reviewer_email: str | None
    created_at: datetime


class TimelineEntry(BaseModel):
    at: datetime
    kind: TimelineKind
    event_type: str
    actor_email: str | None
    summary: str
    detail: dict[str, object]


@dataclass
class EffectiveField:
    field: ExtractedField
    current_value: str
    status: FieldStatus
    corrected_by_email: str | None


def _aware(value: datetime) -> datetime:
    # SQLite fixtures return naive timestamps; Postgres returns timezone-aware ones.
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def pinned_config(session: Session, document: Document) -> WorkflowConfigModel:
    """The configuration version the document was processed with."""
    row = get_workflow_config_version(session, document.org_id, document.workflow_config_version)
    return load_config(row.config_json) if row is not None else default_invoice_config()


def pinned_type(session: Session, document: Document) -> DocumentTypeSpec:
    config = pinned_config(session, document)
    return config.document_type(document.document_type) or config.document_types[0]


def field_spec(type_spec: DocumentTypeSpec, field: ExtractedField) -> FieldSpec:
    spec = type_spec.field(field.name)
    if spec is not None:
        return spec
    # Fields extracted under an older configuration keep their stored type.
    return FieldSpec.model_validate({"name": field.name, "type": field.field_type})


def effective_fields(
    session: Session, org_id: uuid.UUID, document_id: uuid.UUID
) -> list[EffectiveField]:
    """Current value and status per field: the latest correction wins over extraction."""
    run = latest_extraction_run(session, org_id, document_id)
    if run is None:
        return []
    latest: dict[uuid.UUID, tuple[FieldCorrection, str]] = {}
    for correction, email in list_field_corrections(session, org_id, document_id):
        latest[correction.field_id] = (correction, email)
    result: list[EffectiveField] = []
    for field in list_document_fields(session, org_id, document_id, run.id):
        entry = latest.get(field.id)
        if entry is None:
            stored: FieldStatus = "needs_review" if field.status == "needs_review" else "auto"
            result.append(EffectiveField(field, field.value, stored, None))
        else:
            correction, email = entry
            status: FieldStatus = "corrected" if correction.kind == "edit" else "approved"
            result.append(EffectiveField(field, correction.after_value, status, email))
    return result


def _task_response(task: ReviewTask | None, now: datetime) -> ReviewTaskResponse | None:
    if task is None:
        return None
    return ReviewTaskResponse(
        opened_at=task.opened_at,
        due_at=task.due_at,
        sla_minutes=task.sla_minutes,
        completed_at=task.completed_at,
        outcome=task.outcome,
        overdue=task.completed_at is None and _aware(task.due_at) < now,
    )


def document_detail(session: Session, document: Document) -> DocumentDetail:
    org_id = document.org_id
    run = latest_extraction_run(session, org_id, document.id)
    type_spec = pinned_type(session, document)
    effective = effective_fields(session, org_id, document.id)
    current_values = {item.field.name: item.current_value for item in effective}
    values = {
        spec.name: typed_value(spec, current_values[spec.name])
        if spec.name in current_values
        else None
        for spec in type_spec.fields
    }
    metadata = session.scalar(
        select(InvoiceMetadata).where(
            InvoiceMetadata.org_id == org_id, InvoiceMetadata.document_id == document.id
        )
    )
    flagged = sum(1 for item in effective if item.status == "needs_review")
    fields = []
    for item in effective:
        spec = field_spec(type_spec, item.field)
        fields.append(
            FieldDetail(
                id=item.field.id,
                name=item.field.name,
                label=spec.label,
                field_type=item.field.field_type,
                required=item.field.required,
                value=item.field.value,
                current_value=item.current_value,
                evidence=item.field.evidence,
                page_number=item.field.page_number,
                confidence=float(item.field.confidence),
                threshold=float(item.field.threshold),
                status=item.status,
                signals=_load_signals(item.field.signals_json),
                reasons=_load_reasons(item.field.reasons_json),
                corrected_by_email=item.corrected_by_email,
            )
        )
    return DocumentDetail(
        **summary(document, flagged).model_dump(),
        provider=run.provider if run is not None else None,
        version=metadata.version if metadata is not None else 0,
        fields=fields,
        rule_results=[
            RuleResultResponse(
                name=rule.name, expression=rule.expression, passed=rule.passed, message=rule.message
            )
            for rule in evaluate_rules(values, type_spec)
        ],
        review_task=_task_response(
            get_review_task(session, org_id, document.id), datetime.now(UTC)
        ),
    )


def _load_signals(raw: str) -> dict[str, float | None]:
    try:
        decoded = json.loads(raw)
    except ValueError:
        return {}
    if not isinstance(decoded, dict):
        return {}
    return {
        str(key): (float(value) if isinstance(value, int | float) else None)
        for key, value in decoded.items()
    }


def _load_reasons(raw: str) -> list[str]:
    try:
        decoded = json.loads(raw)
    except ValueError:
        return []
    return [str(item) for item in decoded] if isinstance(decoded, list) else []


def read_document(
    session: Session, org_id: uuid.UUID, document_id: uuid.UUID, user_id: uuid.UUID, role: str
) -> DocumentDetail | None:
    document = get_document_by_id(session, org_id, document_id)
    if document is None or not can_access_document(session, org_id, user_id, role, document):
        return None
    return document_detail(session, document)


def apply_correction(
    session: Session,
    document: Document,
    reviewer_user_id: uuid.UUID,
    field_id: uuid.UUID,
    action: Literal["accept", "edit"],
    value: str | None,
) -> FieldCorrection:
    """Append a correction after the caller has locked the document and checked access."""
    field = get_extracted_field(session, document.org_id, document.id, field_id)
    if field is None:
        raise FieldNotFound("Field not found")
    effective = effective_fields(session, document.org_id, document.id)
    current = next((item for item in effective if item.field.id == field.id), None)
    before = current.current_value if current is not None else field.value
    if action == "edit":
        after = (value or "").strip()
        spec = field_spec(pinned_type(session, document), field)
        problem = format_problem(spec, after)
        if problem is not None:
            raise InvalidCorrection(problem)
    else:
        after = before
    correction = FieldCorrection(
        org_id=document.org_id,
        document_id=document.id,
        field_id=field.id,
        field_name=field.name,
        kind=action,
        before_value=before,
        after_value=after,
        reviewer_user_id=reviewer_user_id,
        created_at=datetime.now(UTC),
    )
    session.add(correction)
    session.flush()
    return correction


def unresolved_flag_count(session: Session, org_id: uuid.UUID, document_id: uuid.UUID) -> int:
    return flagged_counts(session, org_id, [document_id]).get(document_id, 0)


def derive_verified_money(
    session: Session, document: Document, default_currency: str
) -> tuple[Decimal, str] | None:
    """Verified amount and currency from the effective total/currency fields."""
    values = {
        item.field.name: item.current_value
        for item in effective_fields(session, document.org_id, document.id)
    }
    total = parse_money(values.get("total", ""))
    if total is None or total < 0:
        return None
    currency = (values.get("currency") or default_currency).strip().upper()
    return total.quantize(Decimal("0.0001")), currency


def open_review_task(
    session: Session,
    org_id: uuid.UUID,
    document_id: uuid.UUID,
    sla_minutes: int,
    now: datetime | None = None,
) -> ReviewTask:
    """Create the review task or restart its SLA clock when a document is (re)opened."""
    now = now or datetime.now(UTC)
    task = get_review_task(session, org_id, document_id, lock=True)
    if task is None:
        task = ReviewTask(
            document_id=document_id,
            org_id=org_id,
            opened_at=now,
            sla_minutes=sla_minutes,
            due_at=now + timedelta(minutes=sla_minutes),
            version=0,
        )
        session.add(task)
    else:
        task.opened_at = now
        task.sla_minutes = sla_minutes
        task.due_at = now + timedelta(minutes=sla_minutes)
        task.completed_at = None
        task.outcome = None
        task.version += 1
    return task


def complete_review_task(
    session: Session,
    org_id: uuid.UUID,
    document_id: uuid.UUID,
    outcome: Literal["approved", "rejected"],
) -> None:
    task = get_review_task(session, org_id, document_id, lock=True)
    if task is not None:
        task.completed_at = datetime.now(UTC)
        task.outcome = outcome
        task.version += 1


def _effective_value_subquery(org_id: uuid.UUID, name: str) -> ScalarSelect[Any]:
    field = aliased(ExtractedField)
    correction = aliased(FieldCorrection)
    latest_after = (
        select(correction.after_value)
        .where(correction.org_id == org_id, correction.field_id == field.id)
        .order_by(correction.created_at.desc(), correction.id.desc())
        .limit(1)
        .correlate(field)
        .scalar_subquery()
    )
    return (
        select(func.coalesce(latest_after, field.value))
        .where(field.org_id == org_id, field.document_id == Document.id, field.name == name)
        .order_by(field.id)
        .limit(1)
        .correlate(Document)
        .scalar_subquery()
    )


def review_queue(
    session: Session,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    role: str,
    *,
    document_type: str | None = None,
    vendor: str | None = None,
    max_age_hours: int | None = None,
    assigned: AssignedFilter = "all",
    offset: int = 0,
    limit: int = 50,
) -> list[QueueItem]:
    now = datetime.now(UTC)
    vendor_value = _effective_value_subquery(org_id, "vendor")
    total_value = _effective_value_subquery(org_id, "total")
    currency_value = _effective_value_subquery(org_id, "currency")
    query = (
        select(
            Document,
            ReviewTask,
            InvoiceMetadata.assigned_reviewer_id,
            InvoiceMetadata.currency,
            User.email,
            vendor_value,
            total_value,
            currency_value,
        )
        .outerjoin(
            ReviewTask, and_(ReviewTask.org_id == org_id, ReviewTask.document_id == Document.id)
        )
        .outerjoin(
            InvoiceMetadata,
            and_(InvoiceMetadata.org_id == org_id, InvoiceMetadata.document_id == Document.id),
        )
        .outerjoin(User, User.id == InvoiceMetadata.assigned_reviewer_id)
        .where(accessible_document_clause(org_id, user_id, role), Document.status == "needs_review")
    )
    if document_type:
        query = query.where(Document.document_type == document_type)
    if vendor:
        query = query.where(vendor_value.icontains(vendor, autoescape=True))
    if max_age_hours is not None:
        query = query.where(Document.created_at >= now - timedelta(hours=max_age_hours))
    if assigned == "me":
        query = query.where(InvoiceMetadata.assigned_reviewer_id == user_id)
    elif assigned == "unassigned":
        query = query.where(InvoiceMetadata.assigned_reviewer_id.is_(None))
    rows = [
        cast(
            tuple[
                Document,
                ReviewTask | None,
                uuid.UUID | None,
                str | None,
                str | None,
                str | None,
                str | None,
                str | None,
            ],
            tuple(row),
        )
        for row in session.execute(
            query.order_by(ReviewTask.due_at.asc().nulls_last(), Document.created_at, Document.id)
            .offset(offset)
            .limit(limit)
        )
    ]
    flagged = flagged_counts(session, org_id, [row[0].id for row in rows])
    items = []
    for row in rows:
        document, task, reviewer_id, metadata_currency, email, vendor_text, total_text, code = row
        open_task = task is not None and task.completed_at is None
        items.append(
            QueueItem(
                document_id=document.id,
                filename=document.filename,
                document_type=document.document_type,
                vendor=vendor_text,
                total=total_text,
                currency=code or metadata_currency,
                flagged_count=flagged.get(document.id, 0),
                opened_at=task.opened_at if task else None,
                due_at=task.due_at if task else None,
                overdue=open_task and task is not None and _aware(task.due_at) < now,
                assigned_reviewer_id=reviewer_id,
                assigned_reviewer_email=email,
                created_at=document.created_at,
            )
        )
    return items


# Audit rows for these events duplicate typed history rows in the timeline.
_TYPED_AUDIT_EVENTS = frozenset(
    {
        "invoice.commented",
        "invoice.field_accepted",
        "invoice.field_edited",
        "invoice.approve",
        "invoice.reject",
        "invoice.reopen",
    }
)
_KIND_ORDER = {"audit": 0, "extraction": 1, "correction": 2, "review": 3, "comment": 4}


def _humanize(event_type: str) -> str:
    return event_type.replace(".", ": ").replace("_", " ").capitalize()


def _audit_detail(event: AuditEvent) -> dict[str, object]:
    try:
        decoded = json.loads(event.detail_json)
    except ValueError:
        return {}
    return dict(decoded) if isinstance(decoded, dict) else {}


def timeline(session: Session, org_id: uuid.UUID, document_id: uuid.UUID) -> list[TimelineEntry]:
    entries: list[tuple[datetime, int, str, TimelineEntry]] = []

    def add(entry: TimelineEntry, identity: object) -> None:
        entries.append((_aware(entry.at), _KIND_ORDER[entry.kind], str(identity), entry))

    for event, email in list_document_audit_events(session, org_id, document_id):
        if event.event_type in _TYPED_AUDIT_EVENTS:
            continue
        add(
            TimelineEntry(
                at=event.created_at,
                kind="audit",
                event_type=event.event_type,
                actor_email=email,
                summary=_humanize(event.event_type),
                detail=_audit_detail(event),
            ),
            event.id,
        )
    for run in list_extraction_runs(session, org_id, document_id):
        try:
            raw = json.loads(run.raw_json)
        except ValueError:
            raw = {}
        payload = raw if isinstance(raw, dict) else {"fields": raw}
        field_rows = payload.get("fields")
        add(
            TimelineEntry(
                at=run.created_at,
                kind="extraction",
                event_type="extraction.completed",
                actor_email=None,
                summary=f"Extracted {len(field_rows) if isinstance(field_rows, list) else 0} "
                f"field(s) with {run.provider}",
                detail={
                    "provider": run.provider,
                    "model": run.model,
                    "prompt_version": run.prompt_version,
                    "document_type": payload.get("document_type"),
                    "tokens_in": payload.get("tokens_in"),
                    "tokens_out": payload.get("tokens_out"),
                    "latency_ms": payload.get("latency_ms"),
                    "rule_results": payload.get("rule_results", []),
                    "notes": payload.get("notes", []),
                },
            ),
            run.id,
        )
    for correction, email in list_field_corrections(session, org_id, document_id):
        verb = "Edited" if correction.kind == "edit" else "Accepted"
        add(
            TimelineEntry(
                at=correction.created_at,
                kind="correction",
                event_type=f"field.{correction.kind}",
                actor_email=email,
                summary=f"{verb} {correction.field_name.replace('_', ' ')}",
                detail={
                    "field": correction.field_name,
                    "before": correction.before_value,
                    "after": correction.after_value,
                },
            ),
            correction.id,
        )
    for review, email in list_document_reviews(session, org_id, document_id):
        add(
            TimelineEntry(
                at=review.created_at,
                kind="review",
                event_type=f"review.{review.decision}",
                actor_email=email,
                summary=f"Review decision: {review.decision}",
                detail={"decision": review.decision, "comment": review.comment},
            ),
            review.id,
        )
    for comment, email in list_document_comments(session, org_id, document_id):
        add(
            TimelineEntry(
                at=comment.created_at,
                kind="comment",
                event_type="comment.added",
                actor_email=email,
                summary="Comment added",
                detail={"comment_id": str(comment.id), "body": comment.body},
            ),
            comment.id,
        )
    entries.sort(key=lambda item: item[:3])
    return [entry for _, _, _, entry in entries]
