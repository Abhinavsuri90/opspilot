"""Administrator settings: agent switches, action policies, connectors and workflow versions."""

import json
import uuid
from datetime import UTC, datetime
from functools import partial
from typing import Any

import yaml
from pydantic import BaseModel, ValidationError
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import actions_service
from app.action_models import POLICY_MODES, ConnectorInstance, OrgActionPolicy
from app.connectors import connector_types, get_connector
from app.connectors.base import (
    ConnectionTest,
    ConnectorConfigError,
    CredentialsUnavailable,
    validate_with,
)
from app.connectors.credentials import decrypt_credentials, encrypt_credentials
from app.models import AuditEvent, WorkflowConfig
from app.repositories import (
    ensure_org_settings,
    get_action_policy,
    get_connector_by_name,
    get_connector_instance,
    get_org_settings,
    get_user_by_id,
    latest_workflow_config,
    list_action_policies,
    list_connectors,
)
from app.timeouts import OperationTimeout, ParserBusy, run_connector_call
from app.workflow_config import (
    ACTION_TYPE_CONNECTORS,
    InvalidWorkflowConfig,
    WorkflowConfigModel,
    load_config,
)

CONNECTION_TEST_TIMEOUT_SECONDS = 10.0
MAX_WORKFLOW_YAML_BYTES = 64 * 1024
KNOWN_ACTION_TYPES = tuple(ACTION_TYPE_CONNECTORS)


class SettingsConflict(Exception):
    pass


class SettingsInvalid(Exception):
    def __init__(self, message: str, details: list[dict[str, str]] | None = None) -> None:
        super().__init__(message)
        self.details = details or []


class ConnectorNotFound(Exception):
    pass


class PoliciesResponse(BaseModel):
    version: int
    kill_switch: bool
    shadow_mode: bool
    policies: dict[str, str]
    defaults_from_config: dict[str, str]
    known_action_types: list[str]
    updated_at: datetime
    updated_by_email: str | None


class ConnectorResponse(BaseModel):
    id: uuid.UUID
    name: str
    connector_type: str
    config: dict[str, Any]
    has_credentials: bool
    active: bool
    version: int
    created_at: datetime
    updated_at: datetime
    last_test_at: datetime | None
    last_test_ok: bool | None
    last_test_message: str | None
    capabilities: dict[str, Any]


class ConnectionTestResponse(BaseModel):
    ok: bool
    message: str
    tested_at: datetime


class WorkflowResponse(BaseModel):
    version: int
    config: dict[str, Any]
    yaml: str
    created_at: datetime


def _audit(
    session: Session,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    event_type: str,
    details: dict[str, object],
) -> None:
    session.add(
        AuditEvent(
            org_id=org_id,
            actor_user_id=user_id,
            event_type=event_type,
            detail_json=json.dumps(details, default=str, sort_keys=True),
            created_at=datetime.now(UTC),
        )
    )


# Policies and switches


def _config_defaults(session: Session, org_id: uuid.UUID) -> dict[str, str]:
    row = latest_workflow_config(session, org_id)
    if row is None:
        return {}
    try:
        return dict(load_config(row.config_json).action_policies)
    except InvalidWorkflowConfig:
        return {}


def read_policies(session: Session, org_id: uuid.UUID) -> PoliciesResponse:
    settings = ensure_org_settings(session, org_id)
    actor = get_user_by_id(session, settings.updated_by) if settings.updated_by else None
    return PoliciesResponse(
        version=settings.version,
        kill_switch=settings.kill_switch,
        shadow_mode=settings.shadow_mode,
        policies={row.action_type: row.mode for row in list_action_policies(session, org_id)},
        defaults_from_config=_config_defaults(session, org_id),
        known_action_types=list(KNOWN_ACTION_TYPES),
        updated_at=settings.updated_at,
        updated_by_email=actor.email if actor else None,
    )


def update_policies(
    session: Session,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    version: int,
    kill_switch: bool | None,
    shadow_mode: bool | None,
    policies: dict[str, str] | None,
) -> PoliciesResponse:
    for action_type, mode in (policies or {}).items():
        if action_type not in KNOWN_ACTION_TYPES:
            raise SettingsInvalid(f"Unknown action type: {action_type}")
        if mode not in POLICY_MODES:
            raise SettingsInvalid(f"Unknown policy mode for {action_type}: {mode}")
    ensure_org_settings(session, org_id)
    settings = get_org_settings(session, org_id, lock="update")
    assert settings is not None
    if settings.version != version:
        raise SettingsConflict("Settings changed. Refresh them before saving again.")
    now = datetime.now(UTC)
    if kill_switch is not None and kill_switch != settings.kill_switch:
        settings.kill_switch = kill_switch
        _audit(
            session,
            org_id,
            user_id,
            "settings.kill_switch_enabled" if kill_switch else "settings.kill_switch_disabled",
            {"kill_switch": kill_switch},
        )
    if shadow_mode is not None and shadow_mode != settings.shadow_mode:
        settings.shadow_mode = shadow_mode
        _audit(
            session, org_id, user_id, "settings.shadow_mode_changed", {"shadow_mode": shadow_mode}
        )
    for action_type, mode in (policies or {}).items():
        row = get_action_policy(session, org_id, action_type, lock=True)
        previous = row.mode if row is not None else None
        if previous == mode:
            continue
        if row is None:
            session.add(
                OrgActionPolicy(
                    org_id=org_id,
                    action_type=action_type,
                    mode=mode,
                    version=1,
                    updated_at=now,
                    updated_by=user_id,
                )
            )
        else:
            row.mode = mode
            row.version += 1
            row.updated_at = now
            row.updated_by = user_id
        _audit(
            session,
            org_id,
            user_id,
            "settings.policy_changed",
            {"action_type": action_type, "from": previous, "to": mode},
        )
    settings.version += 1
    settings.updated_at = now
    settings.updated_by = user_id
    session.flush()
    return read_policies(session, org_id)


# Connectors


def describe_connector(row: ConnectorInstance) -> ConnectorResponse:
    try:
        config = json.loads(row.config_json)
    except ValueError:
        config = {}
    return ConnectorResponse(
        id=row.id,
        name=row.name,
        connector_type=row.connector_type,
        config=config if isinstance(config, dict) else {},
        has_credentials=row.credentials_encrypted is not None,
        active=row.active,
        version=row.version,
        created_at=row.created_at,
        updated_at=row.updated_at,
        last_test_at=row.last_test_at,
        last_test_ok=row.last_test_ok,
        last_test_message=row.last_test_message,
        capabilities=get_connector(row.connector_type).describe_capabilities(),
    )


def list_connector_instances(session: Session, org_id: uuid.UUID) -> list[ConnectorResponse]:
    return [describe_connector(row) for row in list_connectors(session, org_id)]


def _validated_credentials(
    connector_type: str, credentials: dict[str, Any] | None, *, required: bool
) -> str | None:
    connector = get_connector(connector_type)
    model = connector.credentials_model
    if model is None:
        if credentials:
            raise ConnectorConfigError(f"{connector_type} connectors do not take credentials")
        return None
    if credentials is None:
        if required:
            raise ConnectorConfigError(f"{connector_type} connectors require credentials")
        return None
    return encrypt_credentials(validate_with(model, credentials, "credentials"))


def create_connector(
    session: Session,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    name: str,
    connector_type: str,
    config: dict[str, Any],
    credentials: dict[str, Any] | None,
) -> ConnectorResponse:
    if connector_type not in connector_types():
        raise ConnectorConfigError(f"Unknown connector type: {connector_type}")
    connector = get_connector(connector_type)
    validated = validate_with(connector.config_model, config, "config")
    encrypted = _validated_credentials(connector_type, credentials, required=True)
    if get_connector_by_name(session, org_id, name) is not None:
        raise SettingsConflict("A connector with this name already exists")
    now = datetime.now(UTC)
    row = ConnectorInstance(
        id=uuid.uuid4(),
        org_id=org_id,
        name=name,
        connector_type=connector_type,
        config_json=json.dumps(validated, sort_keys=True),
        credentials_encrypted=encrypted,
        active=True,
        version=1,
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise SettingsConflict("A connector with this name already exists") from exc
    _audit(
        session,
        org_id,
        user_id,
        "connector.created",
        {"connector_id": row.id, "name": name, "connector_type": connector_type},
    )
    return describe_connector(row)


def update_connector(
    session: Session,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    connector_id: uuid.UUID,
    *,
    version: int,
    name: str | None,
    config: dict[str, Any] | None,
    credentials: dict[str, Any] | None,
    active: bool | None,
) -> ConnectorResponse:
    row = get_connector_instance(session, org_id, connector_id, lock=True)
    if row is None:
        raise ConnectorNotFound("Connector not found")
    if row.version != version:
        raise SettingsConflict("Connector changed. Refresh it before saving again.")
    connector = get_connector(row.connector_type)
    changes: dict[str, object] = {}
    now = datetime.now(UTC)
    if config is not None:
        row.config_json = json.dumps(
            validate_with(connector.config_model, config, "config"), sort_keys=True
        )
        changes["config"] = True
        # Previews of actions nobody approved yet were built against the old configuration.
        changes["superseded_actions"] = actions_service.supersede_connector_actions(
            session, org_id, row.id, user_id, now
        )
    if credentials is not None:
        row.credentials_encrypted = _validated_credentials(
            row.connector_type, credentials, required=True
        )
        changes["credentials"] = True
    if name is not None and name != row.name:
        other = get_connector_by_name(session, org_id, name)
        if other is not None and other.id != row.id:
            raise SettingsConflict("A connector with this name already exists")
        changes["name"] = name
        row.name = name
    if active is not None and active != row.active:
        row.active = active
        changes["active"] = active
    row.version += 1
    row.updated_at = now
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise SettingsConflict("A connector with this name already exists") from exc
    _audit(
        session, org_id, user_id, "connector.updated", {"connector_id": row.id, "changes": changes}
    )
    return describe_connector(row)


def test_connector(
    session: Session, org_id: uuid.UUID, user_id: uuid.UUID, connector_id: uuid.UUID
) -> ConnectionTestResponse:
    """An explicit administrator probe of a destination; it is not an Action.

    It never runs while the kill switch is on, and the connector row is read without a lock
    so the network call cannot hold a row lock open.
    """
    row = get_connector_instance(session, org_id, connector_id)
    if row is None:
        raise ConnectorNotFound("Connector not found")
    if ensure_org_settings(session, org_id).kill_switch:
        raise SettingsConflict("Agent paused: turn the kill switch off before testing connectors")
    connector = get_connector(row.connector_type)
    try:
        config = json.loads(row.config_json)
    except ValueError:
        config = {}
    try:
        credentials = (
            decrypt_credentials(row.credentials_encrypted) if row.credentials_encrypted else None
        )
        outcome = run_connector_call(
            partial(connector.test_connection, config, credentials), CONNECTION_TEST_TIMEOUT_SECONDS
        )
    except CredentialsUnavailable as exc:
        outcome = ConnectionTest(False, str(exc))
    except OperationTimeout:
        outcome = ConnectionTest(False, "Connection test timed out")
    except ParserBusy:
        outcome = ConnectionTest(False, "Worker is busy; try again shortly")
    except Exception as exc:
        outcome = ConnectionTest(False, f"Connection test failed: {type(exc).__name__}")
    now = datetime.now(UTC)
    session.execute(
        update(ConnectorInstance)
        .where(ConnectorInstance.org_id == org_id, ConnectorInstance.id == row.id)
        .values(last_test_at=now, last_test_ok=outcome.ok, last_test_message=outcome.message[:300])
    )
    _audit(
        session,
        org_id,
        user_id,
        "connector.tested",
        {"connector_id": row.id, "ok": outcome.ok, "message": outcome.message[:300]},
    )
    session.flush()
    return ConnectionTestResponse(ok=outcome.ok, message=outcome.message[:300], tested_at=now)


# Workflow configuration versions


def _yaml_of(config: WorkflowConfigModel) -> str:
    return yaml.safe_dump(
        json.loads(config.model_dump_json()), sort_keys=False, allow_unicode=True, width=100
    )


def _describe_workflow(row: WorkflowConfig, config: WorkflowConfigModel) -> WorkflowResponse:
    return WorkflowResponse(
        version=row.version,
        config=json.loads(config.model_dump_json()),
        yaml=_yaml_of(config),
        created_at=row.created_at,
    )


def read_workflow(session: Session, org_id: uuid.UUID) -> WorkflowResponse | None:
    row = latest_workflow_config(session, org_id)
    if row is None:
        return None
    try:
        config = load_config(row.config_json)
    except InvalidWorkflowConfig as exc:
        raise SettingsInvalid(str(exc)) from exc
    return _describe_workflow(row, config)


def parse_workflow(config: dict[str, Any] | None, yaml_text: str | None) -> WorkflowConfigModel:
    if (config is None) == (yaml_text is None):
        raise SettingsInvalid("Provide either config or yaml, not both")
    raw: object = config
    if yaml_text is not None:
        if len(yaml_text.encode("utf-8")) > MAX_WORKFLOW_YAML_BYTES:
            raise SettingsInvalid("YAML is larger than 64 KB")
        try:
            raw = yaml.safe_load(yaml_text)
        except (yaml.YAMLError, RecursionError) as exc:
            raise SettingsInvalid(f"YAML could not be parsed: {_yaml_problem(exc)}") from exc
    if not isinstance(raw, dict):
        raise SettingsInvalid("Workflow configuration must be a mapping")
    try:
        return WorkflowConfigModel.model_validate(raw)
    except ValidationError as exc:
        details = [
            {
                "field": ".".join(str(part) for part in error["loc"]) or "config",
                "message": error["msg"],
            }
            for error in exc.errors()
        ]
        raise SettingsInvalid("Workflow configuration is invalid", details) from exc


def _yaml_problem(exc: BaseException) -> str:
    if isinstance(exc, RecursionError):
        return "document is nested too deeply"
    mark = getattr(exc, "problem_mark", None)
    problem = getattr(exc, "problem", None) or "syntax error"
    if mark is not None:
        return f"{problem} (line {mark.line + 1}, column {mark.column + 1})"
    return str(problem)


def check_destination_connectors(
    session: Session, org_id: uuid.UUID, config: WorkflowConfigModel
) -> None:
    for destination in config.destinations:
        row = get_connector_by_name(session, org_id, destination.connector)
        expected = ACTION_TYPE_CONNECTORS[destination.action_type]
        if row is None:
            raise SettingsInvalid(
                f"Destination '{destination.name}' references unknown connector "
                f"'{destination.connector}'",
                [{"field": f"destinations.{destination.name}.connector", "message": "not found"}],
            )
        if row.connector_type != expected:
            raise SettingsInvalid(
                f"Destination '{destination.name}' needs a {expected} connector but "
                f"'{destination.connector}' is a {row.connector_type} connector",
                [
                    {
                        "field": f"destinations.{destination.name}.action_type",
                        "message": "type mismatch",
                    }
                ],
            )


def update_workflow(
    session: Session,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    base_version: int,
    config: dict[str, Any] | None,
    yaml_text: str | None,
) -> WorkflowResponse:
    model = parse_workflow(config, yaml_text)
    check_destination_connectors(session, org_id, model)
    latest = latest_workflow_config(session, org_id)
    current_version = latest.version if latest is not None else 0
    if current_version != base_version:
        raise SettingsConflict(
            f"Workflow configuration is at version {current_version}; refresh and reapply your edit"
        )
    row = WorkflowConfig(
        id=uuid.uuid4(),
        org_id=org_id,
        version=base_version + 1,
        config_json=model.model_dump_json(),
        created_at=datetime.now(UTC),
    )
    session.add(row)
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise SettingsConflict(
            "Workflow configuration changed; refresh and reapply your edit"
        ) from exc
    _audit(
        session,
        org_id,
        user_id,
        "workflow.config_updated",
        {
            "version": row.version,
            "base_version": base_version,
            "document_types": [item.name for item in model.document_types],
            "destinations": [item.name for item in model.destinations],
        },
    )
    return _describe_workflow(row, model)
