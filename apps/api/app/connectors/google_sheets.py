"""Append rows to a Google Sheet with a service account.

Authentication is a signed JWT (RS256, service account private key) exchanged for an OAuth
access token. Idempotency: column A holds the idempotency key; the connector reads the column
first and skips a key it already finds. Live verification needs a real service account with
edit access to the sheet; automated tests mock both Google endpoints.
"""

import json
import logging
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import quote

import httpx
import jwt
from cryptography.hazmat.primitives import serialization
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.connectors.base import (
    ActionRequest,
    ConnectionTest,
    Diff,
    ExecutionResult,
    neutralize_cell,
)

logger = logging.getLogger(__name__)
SHEETS_API = "https://sheets.googleapis.com/v4/spreadsheets"
# The only token endpoint a service-account key may name; anything else would make the worker
# post a signed assertion to an attacker-chosen URL.
TOKEN_URI = "https://oauth2.googleapis.com/token"
SCOPE = "https://www.googleapis.com/auth/spreadsheets"
KEY_COLUMN = "opspilot_idempotency_key"
REQUEST_TIMEOUT_SECONDS = 10.0
MAX_SERVICE_ACCOUNT_BYTES = 16 * 1024


class GoogleSheetsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    spreadsheet_id: str = Field(pattern=r"^[A-Za-z0-9_-]{10,200}$")
    sheet_name: str = Field(min_length=1, max_length=100)


class GoogleSheetsCredentials(BaseModel):
    model_config = ConfigDict(extra="forbid")

    service_account_json: str = Field(min_length=2, max_length=MAX_SERVICE_ACCOUNT_BYTES)

    @field_validator("service_account_json")
    @classmethod
    def parse_service_account(cls, value: str) -> str:
        parse_service_account(value)
        return value


def parse_service_account(raw: str) -> dict[str, str]:
    try:
        decoded = json.loads(raw)
    except ValueError as exc:
        raise ValueError("service_account_json is not valid JSON") from exc
    if not isinstance(decoded, dict):
        raise ValueError("service_account_json must be a JSON object")
    email = decoded.get("client_email")
    private_key = decoded.get("private_key")
    token_uri = decoded.get("token_uri", TOKEN_URI)
    if not isinstance(email, str) or "@" not in email:
        raise ValueError("service_account_json lacks client_email")
    if not isinstance(private_key, str) or "PRIVATE KEY" not in private_key:
        raise ValueError("service_account_json lacks a PEM private_key")
    if token_uri != TOKEN_URI:
        raise ValueError(f"service_account_json token_uri must be {TOKEN_URI}")
    try:
        serialization.load_pem_private_key(private_key.encode("utf-8"), password=None)
    except (ValueError, TypeError) as exc:
        raise ValueError("service_account_json private_key is not a readable PEM key") from exc
    return {"client_email": email, "private_key": private_key, "token_uri": TOKEN_URI}


class SheetsError(Exception):
    def __init__(self, message: str, retryable: bool) -> None:
        super().__init__(message)
        self.retryable = retryable


def default_client() -> httpx.Client:
    return httpx.Client(timeout=httpx.Timeout(REQUEST_TIMEOUT_SECONDS), follow_redirects=False)


def a1_range(sheet_name: str, cells: str) -> str:
    escaped = sheet_name.replace("'", "''")
    return quote(f"'{escaped}'!{cells}", safe="")


class GoogleSheetsConnector:
    type_name = "google_sheets"
    config_model = GoogleSheetsConfig
    credentials_model: type[BaseModel] | None = GoogleSheetsCredentials

    def __init__(self, client_factory: Callable[[], httpx.Client] = default_client) -> None:
        self._client_factory = client_factory

    def describe_capabilities(self) -> dict[str, Any]:
        return {
            "action_types": ["append_row"],
            "authentication": "service account JWT (RS256) exchanged for an OAuth token",
            "idempotency": f"column A holds {KEY_COLUMN}; existing keys are skipped "
            "(check-then-act: two workers appending the same key at once can both write)",
            "requirement": "share the spreadsheet with the service account email as an editor",
        }

    def _token(self, client: httpx.Client, account: dict[str, str]) -> str:
        now = int(time.time())
        assertion = jwt.encode(
            {
                "iss": account["client_email"],
                "scope": SCOPE,
                "aud": account["token_uri"],
                "iat": now,
                "exp": now + 3600,
            },
            account["private_key"],
            algorithm="RS256",
        )
        response = self._send(
            client,
            "POST",
            account["token_uri"],
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                "assertion": assertion,
            },
            what="token exchange",
        )
        token = response.json().get("access_token") if response.content else None
        if not isinstance(token, str) or not token:
            raise SheetsError("Token exchange returned no access token", retryable=False)
        return token

    def _send(
        self, client: httpx.Client, method: str, url: str, *, what: str, **kwargs: Any
    ) -> httpx.Response:
        try:
            response = client.request(method, url, **kwargs)
        except httpx.TimeoutException as exc:
            raise SheetsError(f"Google {what} timed out", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise SheetsError(
                f"Google {what} failed: {type(exc).__name__}", retryable=True
            ) from exc
        if 200 <= response.status_code < 300:
            return response
        retryable = response.status_code in {408, 429} or response.status_code >= 500
        raise SheetsError(f"Google {what} returned HTTP {response.status_code}", retryable)

    def _headers(self, token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    def test_connection(
        self, config: dict[str, Any], credentials: dict[str, Any] | None
    ) -> ConnectionTest:
        try:
            account = parse_service_account(
                str((credentials or {}).get("service_account_json", ""))
            )
        except ValueError as exc:
            return ConnectionTest(False, str(exc))
        try:
            with self._client_factory() as client:
                token = self._token(client, account)
                response = self._send(
                    client,
                    "GET",
                    f"{SHEETS_API}/{config['spreadsheet_id']}",
                    params={"fields": "sheets.properties.title"},
                    headers=self._headers(token),
                    what="spreadsheet lookup",
                )
        except SheetsError as exc:
            return ConnectionTest(False, str(exc))
        titles = [
            str(sheet.get("properties", {}).get("title", ""))
            for sheet in response.json().get("sheets", [])
            if isinstance(sheet, dict)
        ]
        if config["sheet_name"] not in titles:
            return ConnectionTest(
                False, f"Spreadsheet found, but sheet '{config['sheet_name']}' is missing"
            )
        return ConnectionTest(True, f"Spreadsheet reachable; sheet '{config['sheet_name']}' found")

    def preview(self, config: dict[str, Any], request: ActionRequest) -> Diff:
        return Diff(
            kind="append_row",
            title=f"Append a row to sheet '{config['sheet_name']}'",
            before=None,
            after=dict(request.values),
            lines=[f"Spreadsheet {config['spreadsheet_id']}"]
            + [f"{column}: {value}" for column, value in request.values.items()],
        )

    def execute(
        self,
        config: dict[str, Any],
        credentials: dict[str, Any] | None,
        request: ActionRequest,
        idempotency_key: str,
    ) -> ExecutionResult:
        try:
            account = parse_service_account(
                str((credentials or {}).get("service_account_json", ""))
            )
        except ValueError as exc:
            return ExecutionResult(False, None, str(exc), retryable=False)
        spreadsheet = str(config["spreadsheet_id"])
        sheet = str(config["sheet_name"])
        try:
            with self._client_factory() as client:
                token = self._token(client, account)
                headers = self._headers(token)
                column = self._send(
                    client,
                    "GET",
                    f"{SHEETS_API}/{spreadsheet}/values/{a1_range(sheet, 'A:A')}",
                    headers=headers,
                    what="column read",
                ).json()
                existing = [
                    str(row[0]) for row in column.get("values", []) if isinstance(row, list) and row
                ]
                if idempotency_key in existing:
                    return ExecutionResult(
                        True, None, "Row already present", retryable=False, duplicate=True
                    )
                rows: list[list[str]] = []
                if not existing:
                    rows.append([KEY_COLUMN, *request.values.keys()])
                rows.append(
                    [
                        idempotency_key,
                        *(neutralize_cell(value) for value in request.values.values()),
                    ]
                )
                appended = self._send(
                    client,
                    "POST",
                    f"{SHEETS_API}/{spreadsheet}/values/{a1_range(sheet, 'A1')}:append",
                    # RAW keeps every value literal; USER_ENTERED would parse formulas.
                    params={"valueInputOption": "RAW", "insertDataOption": "INSERT_ROWS"},
                    headers=headers,
                    json={"values": rows},
                    what="append",
                ).json()
        except SheetsError as exc:
            return ExecutionResult(False, None, str(exc), retryable=exc.retryable)
        updated = appended.get("updates", {}) if isinstance(appended, dict) else {}
        updated_range = updated.get("updatedRange")
        external_id = str(updated_range)[:200] if isinstance(updated_range, str) else None
        return ExecutionResult(
            True, external_id, f"Appended {len(rows)} row(s) to '{sheet}'", retryable=False
        )
