"""Dashboard KPIs over the documents a caller may see.

Definitions (see docs/adr/008-intake-channels-and-templates.md):

- processed: documents created in the range that reached a decision path (not queued,
  extracting, validating or failed);
- auto-approved: processed documents that never needed a review task;
- field accuracy: 1 minus (fields a reviewer edited / fields assessed) over the latest run;
- time to complete: review task completed minus opened; zero for auto-approved documents;
- hours saved: processed documents x baseline minutes minus actual review minutes, floored
  at zero, in hours. Cost per document stays null until LLM calls are metered (Phase 5).

Days are UTC calendar days: the range ends on today's UTC date and each series point
buckets documents by the UTC date they were created.
"""

import statistics
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import cast

from pydantic import BaseModel
from sqlalchemy import and_, case, exists, func, select
from sqlalchemy.orm import Session

from app.access import accessible_document_clause
from app.models import Document, ExtractedField
from app.repositories import latest_run_id_for, latest_workflow_config
from app.workflow_config import InvalidWorkflowConfig, load_config
from app.workflow_models import FieldCorrection, ReviewTask

UNPROCESSED_STATUSES = ("queued", "extracting", "validating", "failed")
DEFAULT_BASELINE_MINUTES = 12


class MetricsRange(BaseModel):
    days: int
    start: date
    end: date
    document_type: str | None


class SeriesPoint(BaseModel):
    day: date
    documents: int
    auto_approved: int
    needs_review: int
    corrected_fields: int
    total_fields: int
    completed: int
    review_minutes: float


class MetricsOverview(BaseModel):
    range: MetricsRange
    documents_processed: int
    auto_approve_rate: float | None
    field_accuracy: float | None
    median_time_to_complete_minutes: float | None
    review_queue_depth: int
    cost_per_document: float | None
    hours_saved: float
    baseline_minutes: int
    series: list[SeriesPoint]


@dataclass
class _DocumentRow:
    day: date
    auto_approved: bool
    completed: bool
    review_minutes: float | None


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def baseline_minutes(session: Session, org_id: uuid.UUID) -> int:
    row = latest_workflow_config(session, org_id)
    if row is None:
        return DEFAULT_BASELINE_MINUTES
    try:
        return load_config(row.config_json).baseline_minutes
    except InvalidWorkflowConfig:
        return DEFAULT_BASELINE_MINUTES


def overview(
    session: Session,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    role: str,
    *,
    days: int,
    document_type: str | None = None,
    today: date | None = None,
) -> MetricsOverview:
    today = today or datetime.now(UTC).date()
    start = today - timedelta(days=days - 1)
    start_at = datetime.combine(start, datetime.min.time(), tzinfo=UTC)
    filters = [
        accessible_document_clause(org_id, user_id, role),
        Document.created_at >= start_at,
        Document.status.not_in(UNPROCESSED_STATUSES),
    ]
    if document_type:
        filters.append(Document.document_type == document_type)

    # Query 1: one row per processed document with its review task, if any.
    document_rows = session.execute(
        select(Document.created_at, ReviewTask.opened_at, ReviewTask.completed_at)
        .outerjoin(
            ReviewTask, and_(ReviewTask.org_id == org_id, ReviewTask.document_id == Document.id)
        )
        .where(*filters)
    )
    rows: list[_DocumentRow] = []
    for created_at, opened_at, completed_at in document_rows:
        created = _aware(created_at)
        if opened_at is None:
            rows.append(_DocumentRow(created.date(), True, True, 0.0))
        elif completed_at is None:
            rows.append(_DocumentRow(created.date(), False, False, None))
        else:
            minutes = (_aware(completed_at) - _aware(opened_at)).total_seconds() / 60
            rows.append(_DocumentRow(created.date(), False, True, max(0.0, minutes)))

    # Query 2: fields of each document's latest run and how many a reviewer edited, per day.
    edited = (
        exists()
        .where(
            FieldCorrection.org_id == org_id,
            FieldCorrection.field_id == ExtractedField.id,
            FieldCorrection.kind == "edit",
        )
        .correlate(ExtractedField)
    )
    latest_run = latest_run_id_for(org_id, ExtractedField.document_id).correlate(ExtractedField)
    field_rows = session.execute(
        select(
            Document.created_at,
            func.count(ExtractedField.id),
            func.sum(case((edited, 1), else_=0)),
        )
        .select_from(ExtractedField)
        .join(
            Document,
            and_(Document.org_id == org_id, Document.id == ExtractedField.document_id),
        )
        .where(
            ExtractedField.org_id == org_id,
            ExtractedField.extraction_run_id == latest_run,
            *filters,
        )
        .group_by(Document.created_at)
    )
    fields_by_day: dict[date, list[int]] = {}
    for row in field_rows:
        created_at, total, corrected = cast(tuple[datetime, int, int | None], tuple(row))
        day = _aware(created_at).date()
        bucket = fields_by_day.setdefault(day, [0, 0])
        bucket[0] += int(total or 0)
        bucket[1] += int(corrected or 0)

    # Query 3: the live review queue, independent of the range.
    queue_filters = [accessible_document_clause(org_id, user_id, role)]
    if document_type:
        queue_filters.append(Document.document_type == document_type)
    queue_depth = int(
        session.scalar(
            select(func.count(Document.id)).where(*queue_filters, Document.status == "needs_review")
        )
        or 0
    )

    rows_by_day: dict[date, list[_DocumentRow]] = {}
    for entry in rows:
        rows_by_day.setdefault(entry.day, []).append(entry)
    series: list[SeriesPoint] = []
    for offset in range(days):
        day = start + timedelta(days=offset)
        day_rows = rows_by_day.get(day, [])
        total_fields, corrected_fields = fields_by_day.get(day, [0, 0])
        series.append(
            SeriesPoint(
                day=day,
                documents=len(day_rows),
                auto_approved=sum(1 for row in day_rows if row.auto_approved),
                needs_review=sum(1 for row in day_rows if not row.auto_approved),
                corrected_fields=corrected_fields,
                total_fields=total_fields,
                completed=sum(1 for row in day_rows if row.completed),
                review_minutes=round(
                    sum(row.review_minutes or 0.0 for row in day_rows if row.completed), 2
                ),
            )
        )

    processed = len(rows)
    auto = sum(1 for row in rows if row.auto_approved)
    durations = [row.review_minutes for row in rows if row.review_minutes is not None]
    total_fields = sum(point.total_fields for point in series)
    corrected_total = sum(point.corrected_fields for point in series)
    baseline = baseline_minutes(session, org_id)
    review_minutes = sum(durations)
    return MetricsOverview(
        range=MetricsRange(days=days, start=start, end=today, document_type=document_type),
        documents_processed=processed,
        auto_approve_rate=round(auto / processed, 4) if processed else None,
        field_accuracy=(round(1 - corrected_total / total_fields, 4) if total_fields else None),
        median_time_to_complete_minutes=(
            round(statistics.median(durations), 2) if durations else None
        ),
        review_queue_depth=queue_depth,
        cost_per_document=None,
        hours_saved=round(max(0.0, processed * baseline - review_minutes) / 60, 2),
        baseline_minutes=baseline,
        series=series,
    )
