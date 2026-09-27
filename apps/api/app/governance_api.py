"""Actions, exports and administrator settings routes. Logic lives in the services."""

import uuid
from typing import Annotated, Any, Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app import actions_service, settings_service
from app.action_models import ACTION_STATUSES
from app.actions_service import ActionDetail, ActionSummary
from app.auth import Identity, current_session
from app.connectors.base import ConnectorConfigError, CredentialsUnavailable
from app.connectors.csv_export import MONTH_PATTERN, export_key, month_of_key
from app.repositories import get_connector_instance, list_accessible_actions, list_export_keys
from app.settings_service import (
    ConnectionTestResponse,
    ConnectorNotFound,
    ConnectorResponse,
    PoliciesResponse,
    SettingsConflict,
    SettingsInvalid,
    WorkflowResponse,
)
from app.storage import ObjectStore, StorageError, StoredObjectMissing, get_store

router = APIRouter(prefix="/v1", tags=["Governance"])
SessionContext = Annotated[Identity, Depends(current_session)]
ACTION_STATUS_PATTERN = "^(" + "|".join(ACTION_STATUSES) + ")$"


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ActionDecisionRequest(RequestModel):
    version: int = Field(ge=0)
    decision: Literal["approve", "reject"]
    comment: str = Field(default="", max_length=4000)

    @model_validator(mode="after")
    def rejection_needs_reason(self) -> "ActionDecisionRequest":
        if self.decision == "reject" and not self.comment:
            raise ValueError("Explain why this action is rejected")
        return self


class ActionRetryRequest(RequestModel):
    version: int = Field(ge=0)


class PoliciesUpdate(RequestModel):
    version: int = Field(ge=0)
    kill_switch: bool | None = None
    shadow_mode: bool | None = None
    policies: dict[str, Literal["auto", "needs_approval", "forbidden"]] | None = Field(
        default=None, max_length=50
    )


class ConnectorCreate(RequestModel):
    name: str = Field(min_length=1, max_length=100)
    connector_type: Literal["webhook", "csv_export", "postgres_table", "google_sheets"]
    config: dict[str, Any] = Field(default_factory=dict)
    credentials: dict[str, Any] | None = None


class ConnectorUpdate(RequestModel):
    version: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=100)
    config: dict[str, Any] | None = None
    credentials: dict[str, Any] | None = None
    active: bool | None = None


class WorkflowUpdate(RequestModel):
    base_version: int = Field(ge=0)
    config: dict[str, Any] | None = None
    yaml: str | None = Field(default=None, max_length=settings_service.MAX_WORKFLOW_YAML_BYTES)


class ExportMonth(BaseModel):
    connector_id: uuid.UUID
    month: str
    path: str


def _require_admin(identity: Identity) -> None:
    if identity[3].role != "admin":
        raise HTTPException(403, "Administrator access required")


def _settings_errors(exc: Exception) -> Exception:
    """Map service failures to responses; SettingsInvalid keeps its structured details."""
    if isinstance(exc, SettingsConflict):
        return HTTPException(409, str(exc))
    if isinstance(exc, SettingsInvalid):
        return exc
    if isinstance(exc, ConnectorConfigError):
        return HTTPException(422, str(exc))
    if isinstance(exc, ConnectorNotFound):
        return HTTPException(404, str(exc))
    if isinstance(exc, CredentialsUnavailable):
        return HTTPException(503, str(exc))
    raise exc


# Actions


@router.get("/actions", response_model=list[ActionSummary])
def list_actions(
    context: SessionContext,
    status: Annotated[str | None, Query(pattern=ACTION_STATUS_PATTERN)] = None,
    document_id: uuid.UUID | None = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[ActionSummary]:
    session, user, org, membership = context
    rows = list_accessible_actions(
        session,
        org.id,
        user.id,
        membership.role,
        status=status,
        document_id=document_id,
        offset=offset,
        limit=limit,
    )
    return [
        actions_service.summarize(action, document, connector_name, decider_email)
        for action, document, connector_name, decider_email in rows
    ]


@router.get("/actions/{action_id}", response_model=ActionDetail)
def action_detail(action_id: uuid.UUID, context: SessionContext) -> ActionDetail:
    session, user, org, membership = context
    result = actions_service.read_action(session, org.id, user.id, membership.role, action_id)
    if result is None:
        raise HTTPException(404, "Action not found")
    return result


def _mutate_action(context: SessionContext, action_id: uuid.UUID, mutate: Any) -> ActionDetail:
    session, user, org, membership = context
    try:
        mutate(session, org.id, user.id, membership.role, action_id)
    except actions_service.ActionNotFound as exc:
        raise HTTPException(404, str(exc)) from exc
    except actions_service.ActionForbidden as exc:
        raise HTTPException(403, str(exc)) from exc
    except actions_service.ActionConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    result = actions_service.read_action(session, org.id, user.id, membership.role, action_id)
    session.commit()
    if result is None:
        raise HTTPException(404, "Action not found")
    return result


@router.post("/actions/{action_id}/decision", response_model=ActionDetail)
def decide_action(
    action_id: uuid.UUID, payload: ActionDecisionRequest, context: SessionContext
) -> ActionDetail:
    def mutate(
        session: Any, org_id: uuid.UUID, user_id: uuid.UUID, role: str, target: uuid.UUID
    ) -> None:
        actions_service.decide_action(
            session,
            org_id,
            user_id,
            role,
            target,
            payload.decision,
            payload.comment,
            payload.version,
        )

    return _mutate_action(context, action_id, mutate)


@router.post("/actions/{action_id}/retry", response_model=ActionDetail)
def retry_action(
    action_id: uuid.UUID, payload: ActionRetryRequest, context: SessionContext
) -> ActionDetail:
    def mutate(
        session: Any, org_id: uuid.UUID, user_id: uuid.UUID, role: str, target: uuid.UUID
    ) -> None:
        actions_service.retry_action(session, org_id, user_id, role, target, payload.version)

    return _mutate_action(context, action_id, mutate)


# Exports


def _export_connector(context: SessionContext, connector_id: uuid.UUID) -> Any:
    session, _, org, membership = context
    if membership.role not in {"admin", "reviewer"}:
        raise HTTPException(403, "Only a reviewer or administrator can download exports")
    connector = get_connector_instance(session, org.id, connector_id)
    if connector is None or connector.connector_type != "csv_export":
        raise HTTPException(404, "Export connector not found")
    return connector


@router.get("/exports", response_model=list[ExportMonth])
def list_exports(context: SessionContext, connector_id: uuid.UUID) -> list[ExportMonth]:
    session, _, org, _ = context
    connector = _export_connector(context, connector_id)
    months = sorted(
        {
            month
            for month in map(month_of_key, list_export_keys(session, org.id, connector.id))
            if month is not None
        },
        reverse=True,
    )
    return [
        ExportMonth(
            connector_id=connector.id, month=month, path=f"/v1/exports/{connector.id}/{month}.csv"
        )
        for month in months
    ]


@router.get("/exports/{connector_id}/{month}.csv", response_class=Response)
def download_export(
    connector_id: uuid.UUID,
    month: str,
    context: SessionContext,
    store: Annotated[ObjectStore, Depends(get_store)],
) -> Response:
    _, _, org, _ = context
    if not MONTH_PATTERN.fullmatch(month):
        raise HTTPException(422, "Month must look like YYYY-MM")
    connector = _export_connector(context, connector_id)
    try:
        data = store.get(export_key(org.id, connector.id, month))
    except StoredObjectMissing as exc:
        raise HTTPException(404, "No export exists for this month") from exc
    except StorageError as exc:
        raise HTTPException(503, "Export storage is unavailable") from exc
    prefix = settings_service.describe_connector(connector).config.get("file_prefix", "export")
    filename = quote(f"{prefix}-{month}.csv", safe="")
    return Response(
        content=data,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{filename}",
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


# Settings: policies and switches


@router.get("/settings/policies", response_model=PoliciesResponse)
def read_policies(context: SessionContext) -> PoliciesResponse:
    _require_admin(context)
    session, _, org, _ = context
    result = settings_service.read_policies(session, org.id)
    session.commit()
    return result


@router.post("/settings/policies", response_model=PoliciesResponse)
def update_policies(payload: PoliciesUpdate, context: SessionContext) -> PoliciesResponse:
    _require_admin(context)
    session, user, org, _ = context
    try:
        result = settings_service.update_policies(
            session,
            org.id,
            user.id,
            version=payload.version,
            kill_switch=payload.kill_switch,
            shadow_mode=payload.shadow_mode,
            policies=dict(payload.policies) if payload.policies is not None else None,
        )
    except (SettingsConflict, SettingsInvalid) as exc:
        raise _settings_errors(exc) from exc
    session.commit()
    return result


# Settings: connectors


@router.get("/settings/connectors", response_model=list[ConnectorResponse])
def list_connectors(context: SessionContext) -> list[ConnectorResponse]:
    _require_admin(context)
    session, _, org, _ = context
    return settings_service.list_connector_instances(session, org.id)


@router.post("/settings/connectors", response_model=ConnectorResponse, status_code=201)
def create_connector(payload: ConnectorCreate, context: SessionContext) -> ConnectorResponse:
    _require_admin(context)
    session, user, org, _ = context
    try:
        result = settings_service.create_connector(
            session,
            org.id,
            user.id,
            name=payload.name,
            connector_type=payload.connector_type,
            config=payload.config,
            credentials=payload.credentials,
        )
    except (SettingsConflict, ConnectorConfigError, CredentialsUnavailable) as exc:
        raise _settings_errors(exc) from exc
    session.commit()
    return result


@router.post("/settings/connectors/{connector_id}", response_model=ConnectorResponse)
def update_connector(
    connector_id: uuid.UUID, payload: ConnectorUpdate, context: SessionContext
) -> ConnectorResponse:
    _require_admin(context)
    session, user, org, _ = context
    try:
        result = settings_service.update_connector(
            session,
            org.id,
            user.id,
            connector_id,
            version=payload.version,
            name=payload.name,
            config=payload.config,
            credentials=payload.credentials,
            active=payload.active,
        )
    except (
        SettingsConflict,
        ConnectorConfigError,
        ConnectorNotFound,
        CredentialsUnavailable,
    ) as exc:
        raise _settings_errors(exc) from exc
    session.commit()
    return result


@router.post("/settings/connectors/{connector_id}/test", response_model=ConnectionTestResponse)
def test_connector(connector_id: uuid.UUID, context: SessionContext) -> ConnectionTestResponse:
    _require_admin(context)
    session, user, org, _ = context
    try:
        result = settings_service.test_connector(session, org.id, user.id, connector_id)
    except ConnectorNotFound as exc:
        raise _settings_errors(exc) from exc
    session.commit()
    return result


# Settings: workflow configuration


@router.get("/settings/workflow", response_model=WorkflowResponse)
def read_workflow(context: SessionContext) -> WorkflowResponse:
    _require_admin(context)
    session, _, org, _ = context
    try:
        result = settings_service.read_workflow(session, org.id)
    except SettingsInvalid as exc:
        raise _settings_errors(exc) from exc
    if result is None:
        raise HTTPException(404, "No workflow configuration exists for this organization")
    return result


@router.post("/settings/workflow", response_model=WorkflowResponse)
def update_workflow(payload: WorkflowUpdate, context: SessionContext) -> WorkflowResponse:
    _require_admin(context)
    session, user, org, _ = context
    try:
        result = settings_service.update_workflow(
            session,
            org.id,
            user.id,
            base_version=payload.base_version,
            config=payload.config,
            yaml_text=payload.yaml,
        )
    except (SettingsConflict, SettingsInvalid) as exc:
        raise _settings_errors(exc) from exc
    session.commit()
    return result
