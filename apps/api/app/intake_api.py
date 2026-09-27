"""Routes for intake channels and KPIs: API keys, the email inbox and the metrics overview."""

import json
import uuid
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from app import api_keys, email_settings, metrics_service
from app.api_keys import ApiKeyCreatedResponse, ApiKeyResponse
from app.auth import Identity, current_session
from app.connectors.base import ConnectorConfigError, CredentialsUnavailable
from app.email_settings import EmailInboxResponse, InboxConflict, InboxTestResponse
from app.metrics_service import AccuracyPoint, MetricsOverview
from app.workflow_config import DOCUMENT_TYPE_PATTERN

router = APIRouter(prefix="/v1", tags=["Intake"])
SessionContext = Annotated[Identity, Depends(current_session)]
REPORTS_DIR = Path("/workspace/evals/reports")
MAX_EVAL_REPORT_BYTES = 512 * 1024


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ApiKeyCreate(RequestModel):
    name: str = Field(min_length=1, max_length=100)


class EmailInboxUpdate(RequestModel):
    version: int = Field(ge=0)
    backend: Literal["imap", "mailpit"]
    address: str | None = Field(default=None, max_length=320)
    config: dict[str, Any] = Field(default_factory=dict)
    credentials: dict[str, Any] | None = None
    active: bool = True


class EvalReportResponse(BaseModel):
    generated_at: str
    provider: str
    model: str
    tier2_model: str | None
    dataset: str
    exact_match: float
    grounded_fraction: float
    flag_precision: float
    flag_recall: float
    type_detection: float
    escalation_rate: float
    cost: dict[str, Any]
    learning: dict[str, Any]
    limitations: str


@router.get("/evals/latest", response_model=EvalReportResponse)
def latest_eval_report(context: SessionContext) -> EvalReportResponse:
    """Latest operator-run synthetic evaluation; available to organization admins only."""
    _require_admin(context)
    for path in sorted(REPORTS_DIR.glob("????????T??????Z-*.json"), reverse=True):
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_EVAL_REPORT_BYTES:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                continue
            return EvalReportResponse.model_validate(
                {**data, "generated_at": path.name.split("-", 1)[0]}
            )
        except (OSError, ValueError):
            continue
    raise HTTPException(404, "No evaluation report is available. Run make eval first.")


def _require_admin(identity: Identity) -> None:
    if identity[3].role != "admin":
        raise HTTPException(403, "Administrator access required")


# API keys


@router.get("/settings/api-keys", response_model=list[ApiKeyResponse])
def list_api_keys(context: SessionContext) -> list[ApiKeyResponse]:
    _require_admin(context)
    session, _, org, _ = context
    return api_keys.list_keys(session, org.id)


@router.post("/settings/api-keys", response_model=ApiKeyCreatedResponse, status_code=201)
def create_api_key(payload: ApiKeyCreate, context: SessionContext) -> ApiKeyCreatedResponse:
    _require_admin(context)
    session, user, org, _ = context
    try:
        result = api_keys.create_api_key(session, org.id, user.id, payload.name)
    except api_keys.ApiKeyLimitReached as exc:
        raise HTTPException(409, str(exc)) from exc
    session.commit()
    return result


@router.post("/settings/api-keys/{key_id}/revoke", response_model=ApiKeyResponse)
def revoke_api_key(key_id: uuid.UUID, context: SessionContext) -> ApiKeyResponse:
    _require_admin(context)
    session, user, org, _ = context
    try:
        result = api_keys.revoke_api_key(session, org.id, user.id, key_id)
    except api_keys.ApiKeyNotFound as exc:
        raise HTTPException(404, str(exc)) from exc
    session.commit()
    return result


# Email inbox


@router.get("/settings/email-inbox", response_model=EmailInboxResponse | None)
def read_email_inbox(context: SessionContext) -> EmailInboxResponse | None:
    _require_admin(context)
    session, _, org, _ = context
    return email_settings.read_inbox(session, org.id)


@router.post("/settings/email-inbox", response_model=EmailInboxResponse)
def save_email_inbox(payload: EmailInboxUpdate, context: SessionContext) -> EmailInboxResponse:
    _require_admin(context)
    session, user, org, _ = context
    try:
        result = email_settings.save_inbox(
            session,
            org,
            user.id,
            backend=payload.backend,
            address=payload.address,
            config=payload.config,
            credentials=payload.credentials,
            active=payload.active,
            version=payload.version,
        )
    except InboxConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except ConnectorConfigError as exc:
        raise HTTPException(422, str(exc)) from exc
    except CredentialsUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    session.commit()
    return result


@router.post("/settings/email-inbox/test", response_model=InboxTestResponse)
def test_email_inbox(context: SessionContext) -> InboxTestResponse:
    _require_admin(context)
    session, user, org, _ = context
    try:
        result = email_settings.test_inbox(session, org, user.id)
    except InboxConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    session.commit()
    return result


# KPIs


@router.get("/metrics/overview", response_model=MetricsOverview)
def metrics_overview(
    context: SessionContext,
    days: Annotated[int, Query(ge=1, le=365)] = 30,
    document_type: Annotated[str | None, Query(pattern=DOCUMENT_TYPE_PATTERN)] = None,
) -> MetricsOverview:
    """KPIs over the documents the caller may see.

    ``days`` counts back from today's UTC date and every ``series`` point is a UTC calendar
    day; ``cost_per_document`` (cents) is null until the range has a recorded model call.
    """
    session, user, org, membership = context
    return metrics_service.overview(
        session, org.id, user.id, membership.role, days=days, document_type=document_type
    )


@router.get("/metrics/accuracy", response_model=list[AccuracyPoint])
def metrics_accuracy(
    context: SessionContext,
    weeks: Annotated[int, Query(ge=1, le=52)] = 12,
    document_type: Annotated[str | None, Query(pattern=DOCUMENT_TYPE_PATTERN)] = None,
) -> list[AccuracyPoint]:
    """Field accuracy per ISO week (Monday start, UTC), oldest week first.

    ``fields_assessed`` counts the fields of each document's latest extraction run and
    ``fields_corrected`` those a reviewer edited; ``accuracy`` is null for an empty week.
    """
    session, user, org, membership = context
    return metrics_service.accuracy_series(
        session, org.id, user.id, membership.role, weeks=weeks, document_type=document_type
    )
