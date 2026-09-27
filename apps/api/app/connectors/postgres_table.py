"""Insert one row per approved document into a customer-owned Postgres table.

Requirement on the destination table: a unique column ``opspilot_action_id`` (uuid or text).
Inserts use ``ON CONFLICT (opspilot_action_id) DO NOTHING`` so a repeated execution is a no-op.
Identifiers are quoted with ``psycopg.sql``; values are bound parameters that Postgres casts to
the column types.
"""

import logging
import re
from typing import Any

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.connectors.base import ActionRequest, ConnectionTest, Diff, ExecutionResult

logger = logging.getLogger(__name__)
IDENTIFIER_PATTERN = r"^[A-Za-z_][A-Za-z0-9_]{0,62}$"
ACTION_ID_COLUMN = "opspilot_action_id"
CONNECT_TIMEOUT_SECONDS = 5
STATEMENT_TIMEOUT_MS = 10_000


class PostgresTableConfig(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        validate_by_name=True,
        validate_by_alias=True,
        serialize_by_alias=True,
    )

    schema_name: str = Field(alias="schema", pattern=IDENTIFIER_PATTERN)
    table: str = Field(pattern=IDENTIFIER_PATTERN)


class PostgresCredentials(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    dsn: str = Field(min_length=12, max_length=2000)

    @field_validator("dsn")
    @classmethod
    def parse_dsn(cls, value: str) -> str:
        value = normalize_dsn(value)
        try:
            parts = conninfo_to_dict(value)
        except psycopg.ProgrammingError as exc:
            raise ValueError("dsn is not a valid Postgres connection string") from exc
        if not parts.get("host") and not parts.get("hostaddr"):
            raise ValueError("dsn must name a host")
        return value


def normalize_dsn(value: str) -> str:
    """Accept SQLAlchemy-style URLs by dropping the driver suffix."""
    return re.sub(r"^postgres(ql)?\+psycopg(2)?://", "postgresql://", value.strip())


def _connect(dsn: str) -> psycopg.Connection[Any]:
    return psycopg.connect(
        dsn,
        connect_timeout=CONNECT_TIMEOUT_SECONDS,
        application_name="opspilot-connector",
        options=f"-c statement_timeout={STATEMENT_TIMEOUT_MS}",
    )


class PostgresTableConnector:
    type_name = "postgres_table"
    config_model = PostgresTableConfig
    credentials_model: type[BaseModel] | None = PostgresCredentials

    def describe_capabilities(self) -> dict[str, Any]:
        return {
            "action_types": ["create_record"],
            "requirement": f"a unique column {ACTION_ID_COLUMN} (uuid or text) on the table",
            "idempotency": f"INSERT ... ON CONFLICT ({ACTION_ID_COLUMN}) DO NOTHING",
        }

    def test_connection(
        self, config: dict[str, Any], credentials: dict[str, Any] | None
    ) -> ConnectionTest:
        dsn = str((credentials or {}).get("dsn", ""))
        if not dsn:
            return ConnectionTest(False, "Connection string is missing")
        schema, table = str(config["schema"]), str(config["table"])
        try:
            with _connect(dsn) as connection, connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.execute(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = %s AND table_name = %s",
                    (schema, table),
                )
                columns = {str(row[0]) for row in cursor.fetchall()}
        except psycopg.Error as exc:
            return ConnectionTest(False, f"Connection failed: {type(exc).__name__}")
        if not columns:
            return ConnectionTest(False, f"Connected, but table {schema}.{table} was not found")
        if ACTION_ID_COLUMN not in columns:
            return ConnectionTest(
                False, f"Connected, but {schema}.{table} lacks the unique column {ACTION_ID_COLUMN}"
            )
        return ConnectionTest(True, f"Connected; {schema}.{table} has {len(columns)} column(s)")

    def preview(self, config: dict[str, Any], request: ActionRequest) -> Diff:
        target = f"{config['schema']}.{config['table']}"
        return Diff(
            kind="create_record",
            title=f"INSERT INTO {target}",
            before=None,
            after=dict(request.values) | {ACTION_ID_COLUMN: str(request.action_id)},
            lines=[f"INSERT INTO {target}"]
            + [f"{column} = {value}" for column, value in request.values.items()],
        )

    def execute(
        self,
        config: dict[str, Any],
        credentials: dict[str, Any] | None,
        request: ActionRequest,
        idempotency_key: str,
    ) -> ExecutionResult:
        dsn = str((credentials or {}).get("dsn", ""))
        if not dsn:
            return ExecutionResult(False, None, "Connection string is missing", retryable=False)
        columns = [*request.values.keys(), ACTION_ID_COLUMN]
        statement = sql.SQL(
            "INSERT INTO {schema}.{table} ({columns}) VALUES ({values}) "
            "ON CONFLICT ({key}) DO NOTHING"
        ).format(
            schema=sql.Identifier(str(config["schema"])),
            table=sql.Identifier(str(config["table"])),
            columns=sql.SQL(", ").join(sql.Identifier(column) for column in columns),
            values=sql.SQL(", ").join(sql.Placeholder() for _ in columns),
            key=sql.Identifier(ACTION_ID_COLUMN),
        )
        parameters = [*request.values.values(), str(request.action_id)]
        try:
            with _connect(dsn) as connection, connection.cursor() as cursor:
                cursor.execute(statement, parameters)
                inserted = cursor.rowcount
        except psycopg.OperationalError as exc:
            return ExecutionResult(
                False, None, f"Connection failed: {type(exc).__name__}", retryable=True
            )
        except psycopg.Error as exc:
            primary = getattr(exc.diag, "message_primary", None) or str(exc)
            return ExecutionResult(
                False, None, f"{type(exc).__name__}: {primary}"[:500], retryable=False
            )
        if inserted == 0:
            return ExecutionResult(
                True, str(request.action_id), "Row already present", retryable=False, duplicate=True
            )
        return ExecutionResult(
            True,
            str(request.action_id),
            f"Inserted 1 row into {config['schema']}.{config['table']}",
            retryable=False,
        )
