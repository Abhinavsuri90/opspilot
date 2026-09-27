"""The connector contract every destination implements.

A connector never touches the database and never logs payload values. It receives
the already-built :class:`ActionRequest`, previews it without credentials or network,
and executes it with an idempotency key so a repeated call cannot duplicate the effect.
"""

import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Protocol

from pydantic import BaseModel, ValidationError


class ConnectorConfigError(ValueError):
    """Configuration or credentials failed validation; the message is safe to show."""


class CredentialsUnavailable(Exception):
    """Stored credentials cannot be decrypted (missing or rotated key)."""


@dataclass(frozen=True)
class ActionRequest:
    org_id: uuid.UUID
    connector_id: uuid.UUID
    action_id: uuid.UUID
    document_id: uuid.UUID
    action_type: str
    # Destination column -> value, in mapping order. Values are already strings.
    values: dict[str, str]
    proposed_at: datetime


@dataclass(frozen=True)
class ConnectionTest:
    ok: bool
    message: str


@dataclass(frozen=True)
class Diff:
    """Human-readable preview of exactly what an action changes."""

    kind: str
    title: str
    before: dict[str, Any] | None
    after: dict[str, Any]
    lines: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ExecutionResult:
    ok: bool
    external_id: str | None
    response_summary: str
    retryable: bool
    # True when the destination already held this idempotency key.
    duplicate: bool = False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class Connector(Protocol):
    @property
    def type_name(self) -> str: ...

    @property
    def config_model(self) -> type[BaseModel]: ...

    @property
    def credentials_model(self) -> type[BaseModel] | None: ...

    def describe_capabilities(self) -> dict[str, Any]: ...

    def test_connection(
        self, config: dict[str, Any], credentials: dict[str, Any] | None
    ) -> ConnectionTest: ...

    def preview(self, config: dict[str, Any], request: ActionRequest) -> Diff: ...

    def execute(
        self,
        config: dict[str, Any],
        credentials: dict[str, Any] | None,
        request: ActionRequest,
        idempotency_key: str,
    ) -> ExecutionResult: ...


def validate_with(model: type[BaseModel], raw: dict[str, Any], what: str) -> dict[str, Any]:
    """Validate ``raw`` with a connector's Pydantic model and return the normalized dict."""
    try:
        return model.model_validate(raw).model_dump(mode="json")
    except ValidationError as exc:
        first = exc.errors()[0]
        location = ".".join(str(part) for part in first["loc"])
        prefix = f"{what}.{location}" if location else what
        raise ConnectorConfigError(f"{prefix}: {first['msg']}") from exc


def summarize_error(exc: BaseException, limit: int = 500) -> str:
    """Error text safe to store: the exception class and its message, bounded."""
    text = f"{type(exc).__name__}: {exc}".strip()
    return text[:limit]


def neutralize_cell(value: str) -> str:
    """Stop spreadsheet formula injection: a leading =, @, tab or CR, or a sign that does not
    start a number, is quoted so the destination shows it as text."""
    if not value:
        return value
    first = value[0]
    if first in "=@\t\r":
        return "'" + value
    if first in "+-" and not (len(value) > 1 and (value[1].isdigit() or value[1] == ".")):
        return "'" + value
    return value
