"""Monthly CSV files in object storage, one row per approved document.

Key: ``exports/{org_id}/{connector_id}/{YYYY-MM}.csv``. Appends are read-modify-write under a
per-tenant advisory lock; the first column is the idempotency key so a repeated execution is
skipped. Rows are downloaded through ``GET /v1/exports``.
"""

import csv
import io
import re
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text

from app.connectors.base import (
    ActionRequest,
    ConnectionTest,
    Diff,
    ExecutionResult,
    neutralize_cell,
)
from app.storage import (
    ObjectStore,
    StorageError,
    StoredDocumentTooLarge,
    StoredObjectMissing,
    get_store,
)

KEY_COLUMN = "opspilot_idempotency_key"
MONTH_PATTERN = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
_KEY_SUFFIX = re.compile(r"/(\d{4}-\d{2})\.csv$")


class CsvExportConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    # Used for the download filename; the storage key is fixed per connector and month.
    file_prefix: str = Field(default="export", pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def export_key(org_id: object, connector_id: object, month: str) -> str:
    return f"exports/{org_id}/{connector_id}/{month}.csv"


def month_of_key(key: str) -> str | None:
    match = _KEY_SUFFIX.search(key)
    return match.group(1) if match else None


@contextmanager
def tenant_export_lock(org_id: object) -> Iterator[None]:
    """Serialize read-modify-write per tenant across workers with a Postgres advisory lock."""
    from app.db import SessionLocal

    with SessionLocal() as session, session.begin():
        session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"csv-export:{org_id}"},
        )
        yield


LockFactory = Callable[[object], Any]


class CsvExportConnector:
    type_name = "csv_export"
    config_model = CsvExportConfig
    credentials_model: type[BaseModel] | None = None

    def __init__(
        self,
        store_factory: Callable[[], ObjectStore] = get_store,
        lock: LockFactory = tenant_export_lock,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._store_factory = store_factory
        self._lock = lock
        self._clock = clock

    def describe_capabilities(self) -> dict[str, Any]:
        return {
            "action_types": ["export_csv"],
            "layout": "one CSV per connector per month, first column is the idempotency key",
            "download": "GET /v1/exports/{connector_id}/{YYYY-MM}.csv",
        }

    def test_connection(
        self, config: dict[str, Any], credentials: dict[str, Any] | None
    ) -> ConnectionTest:
        try:
            self._store_factory().get("exports/.healthcheck")
        except StoredObjectMissing:
            return ConnectionTest(True, "Object storage reachable")
        except StorageError:
            return ConnectionTest(False, "Object storage is unavailable")
        return ConnectionTest(True, "Object storage reachable")

    def preview(self, config: dict[str, Any], request: ActionRequest) -> Diff:
        month = self._clock().strftime("%Y-%m")
        return Diff(
            kind="export_csv",
            title=f"Append a row to {config.get('file_prefix', 'export')}-{month}.csv",
            before=None,
            after=dict(request.values),
            lines=[f"{column}: {value}" for column, value in request.values.items()],
        )

    def execute(
        self,
        config: dict[str, Any],
        credentials: dict[str, Any] | None,
        request: ActionRequest,
        idempotency_key: str,
    ) -> ExecutionResult:
        key = export_key(request.org_id, request.connector_id, self._clock().strftime("%Y-%m"))
        store = self._store_factory()
        try:
            with self._lock(request.org_id):
                try:
                    header, rows = read_rows(store.get(key).decode("utf-8-sig"))
                except StoredObjectMissing:
                    header, rows = [KEY_COLUMN], []
                if any(row.get(KEY_COLUMN) == idempotency_key for row in rows):
                    return ExecutionResult(
                        True, key, "Row already exported", retryable=False, duplicate=True
                    )
                for column in request.values:
                    if column not in header:
                        header.append(column)
                rows.append(
                    {KEY_COLUMN: idempotency_key}
                    | {column: neutralize_cell(value) for column, value in request.values.items()}
                )
                store.put(key, write_rows(header, rows).encode("utf-8"))
        except StoredDocumentTooLarge:
            return ExecutionResult(
                False, None, "Export file exceeds the size limit", retryable=False
            )
        except StorageError:
            return ExecutionResult(False, None, "Object storage is unavailable", retryable=True)
        return ExecutionResult(True, key, f"Appended row {len(rows)} to {key}", retryable=False)


def read_rows(content: str) -> tuple[list[str], list[dict[str, str]]]:
    reader = csv.reader(io.StringIO(content))
    header = next(reader, None) or [KEY_COLUMN]
    if header[0] != KEY_COLUMN:
        header = [KEY_COLUMN, *header]
    rows = []
    for record in reader:
        if not record:
            continue
        rows.append(
            {
                column: (record[index] if index < len(record) else "")
                for index, column in enumerate(header)
            }
        )
    return header, rows


def write_rows(header: list[str], rows: list[dict[str, str]]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(header)
    for row in rows:
        writer.writerow([row.get(column, "") for column in header])
    return buffer.getvalue()
