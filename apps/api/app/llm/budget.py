"""Per-organization daily model budget, checked before every paid call.

The cap lives in ``org_settings.daily_llm_spend_cap_cents`` (null means unlimited) and the
spend is the sum of ``llm_calls.cost_cents`` for the current UTC day. When the cap is
reached the worker either extracts with the rules provider or defers the document to
00:05 UTC the next day, according to ``LLM_BUDGET_FALLBACK``; the organization gets one
audit event per day either way.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from app.db import SessionLocal, set_org_context
from app.models import AuditEvent
from app.repositories import (
    count_audit_events_since,
    get_org_settings,
    sum_llm_cost_since,
)

BUDGET_REACHED_EVENT = "llm.budget_reached"
BUDGET_REASON = "Daily model budget reached"
RESUME_TIME = time(hour=0, minute=5)


@dataclass(frozen=True)
class BudgetStatus:
    cap_cents: int | None
    spent_cents: Decimal
    exhausted: bool


def day_start(now: datetime) -> datetime:
    return datetime.combine(now.astimezone(UTC).date(), time.min, tzinfo=UTC)


def next_window_start(now: datetime) -> datetime:
    """00:05 UTC on the following day, when the ledger's daily sum starts from zero."""
    tomorrow = now.astimezone(UTC).date() + timedelta(days=1)
    return datetime.combine(tomorrow, RESUME_TIME, tzinfo=UTC)


def status(session: Session, org_id: uuid.UUID, now: datetime | None = None) -> BudgetStatus:
    now = now or datetime.now(UTC)
    settings = get_org_settings(session, org_id)
    cap = settings.daily_llm_spend_cap_cents if settings is not None else None
    spent = sum_llm_cost_since(session, org_id, day_start(now))
    return BudgetStatus(cap, spent, cap is not None and spent >= cap)


def allows(session: Session, org_id: uuid.UUID, now: datetime | None = None) -> bool:
    return not status(session, org_id, now).exhausted


def allows_for_org(org_id: uuid.UUID) -> bool:
    """Session-less check for callers outside a transaction (the router, the embedder)."""
    with SessionLocal() as session:
        set_org_context(session, org_id)
        return allows(session, org_id)


def audit_exhausted(
    session: Session, org_id: uuid.UUID, state: BudgetStatus, now: datetime, outcome: str
) -> bool:
    """Record the day's first budget stop for the organization; later stops are silent."""
    if count_audit_events_since(session, org_id, BUDGET_REACHED_EVENT, day_start(now)):
        return False
    session.add(
        AuditEvent(
            id=uuid.uuid4(),
            org_id=org_id,
            actor_user_id=None,
            document_id=None,
            event_type=BUDGET_REACHED_EVENT,
            detail_json=json.dumps(
                {
                    "cap_cents": state.cap_cents,
                    "spent_cents": str(state.spent_cents),
                    "outcome": outcome,
                    "resumes_at": next_window_start(now).isoformat(),
                },
                sort_keys=True,
            ),
            created_at=now,
        )
    )
    return True
