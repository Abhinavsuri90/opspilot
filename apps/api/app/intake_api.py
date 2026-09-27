"""Routes for intake channels and KPIs: API keys, the email inbox and the metrics overview."""

import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from app import api_keys, email_settings, metrics_service
from app.api_keys import ApiKeyCreatedResponse, ApiKeyResponse
from app.auth import Identity, current_session
from app.connectors.base import ConnectorConfigError, CredentialsUnavailable
from app.email_settings import EmailInboxResponse, InboxConflict, InboxTestResponse
from app.metrics_service import MetricsOverview
from app.workflow_config import DOCUMENT_TYPE_PATTERN

router = APIRouter(prefix="/v1", tags=["Intake"])
SessionContext = Annotated[Identity, Depends(current_session)]


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
    session, user, org, membership = context
    return metrics_service.overview(
        session, org.id, user.id, membership.role, days=days, document_type=document_type
    )
