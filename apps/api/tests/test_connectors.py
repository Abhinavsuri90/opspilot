"""Connector contract: encryption, the SSRF guard, signing, idempotent appends and inserts."""

import hashlib
import hmac
import json
import os
import socket
import uuid
from contextlib import nullcontext
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import httpx
import jwt
import psycopg
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from psycopg.conninfo import conninfo_to_dict

from app.connectors import connector_type_for, connector_types, get_connector
from app.connectors import credentials as credentials_module
from app.connectors.base import (
    ActionRequest,
    ConnectorConfigError,
    CredentialsUnavailable,
    neutralize_cell,
    validate_with,
)
from app.connectors.credentials import (
    decrypt_credentials,
    derive_development_key,
    encrypt_credentials,
)
from app.connectors.csv_export import KEY_COLUMN, CsvExportConnector, export_key, month_of_key
from app.connectors.google_sheets import GoogleSheetsConnector, GoogleSheetsCredentials
from app.connectors.network import DestinationBlocked, check_destination
from app.connectors.postgres_table import (
    PostgresCredentials,
    PostgresTableConfig,
    PostgresTableConnector,
)
from app.connectors.webhook import WebhookConfig, WebhookConnector, canonical_body
from app.db import normalize_database_url
from app.storage import StorageError, StoredObjectMissing
from tests.conftest import postgres

ORG_ID, CONNECTOR_ID, ACTION_ID, DOCUMENT_ID = (uuid.uuid4() for _ in range(4))
PROPOSED_AT = datetime(2026, 9, 27, 10, 30, tzinfo=UTC)


def request(
    values: dict[str, str] | None = None, action_type: str = "post_webhook"
) -> ActionRequest:
    return ActionRequest(
        org_id=ORG_ID,
        connector_id=CONNECTOR_ID,
        action_id=ACTION_ID,
        document_id=DOCUMENT_ID,
        action_type=action_type,
        values=values or {"vendor": "Harbor Supply", "total": "110.00", "currency": "USD"},
        proposed_at=PROPOSED_AT,
    )


class MemoryStore:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.fail = False

    def put(self, key: str, data: bytes) -> None:
        if self.fail:
            raise StorageError("down")
        self.objects[key] = data

    def get(self, key: str) -> bytes:
        if self.fail:
            raise StorageError("down")
        if key not in self.objects:
            raise StoredObjectMissing(key)
        return self.objects[key]


# Credentials


def test_credentials_round_trip_and_key_rotation_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    credentials_module._fernet.cache_clear()
    token = encrypt_credentials({"secret": "s" * 20, "nested": {"a": 1}})
    assert "s" * 20 not in token
    assert decrypt_credentials(token) == {"secret": "s" * 20, "nested": {"a": 1}}
    garbage = credentials_module._fernet().encrypt(b"not json").decode("ascii")
    with pytest.raises(CredentialsUnavailable, match="cannot be decrypted"):
        decrypt_credentials(garbage)
    assert derive_development_key("one") != derive_development_key("two")
    assert derive_development_key("one") == derive_development_key("one")
    credentials_module._fernet.cache_clear()
    monkeypatch.setattr(
        "app.connectors.credentials.get_settings",
        lambda: SimpleNamespace(
            connector_encryption_key=None, environment="development", jwt_secret="rotated"
        ),
    )
    with pytest.raises(CredentialsUnavailable, match="cannot be decrypted"):
        decrypt_credentials(token)
    credentials_module._fernet.cache_clear()
    monkeypatch.setattr(
        "app.connectors.credentials.get_settings",
        lambda: SimpleNamespace(
            connector_encryption_key=None, environment="staging", jwt_secret="x"
        ),
    )
    with pytest.raises(CredentialsUnavailable, match="not configured"):
        encrypt_credentials({"secret": "value"})
    credentials_module._fernet.cache_clear()


# SSRF guard


def fake_resolver(mapping: dict[str, list[str]]) -> Any:
    def getaddrinfo(host: str, *args: Any, **kwargs: Any) -> list[Any]:
        if host not in mapping:
            raise socket.gaierror("unknown host")
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 0)) for address in mapping[host]
        ]

    return getaddrinfo


@pytest.mark.parametrize(
    "url",
    [
        "http://hooks.example.test/in",  # plain http
        "https://localhost/in",
        "https://127.0.0.1/in",
        "https://10.1.2.3/in",
        "https://192.168.1.10/in",
        "https://169.254.169.254/latest/meta-data",
        "https://[::1]/in",
        "https://[::ffff:127.0.0.1]/in",
        "https://100.64.0.1/in",
        "https://metadata.internal/in",
        "https://user:pass@hooks.example.test/in",
        "https://private.example.test/in",
        "https://unknown.example.test/in",
        "ftp://hooks.example.test/in",
    ],
)
def test_ssrf_guard_rejects_private_and_unsafe_destinations(
    monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    monkeypatch.setattr(
        "app.connectors.network.socket.getaddrinfo",
        fake_resolver(
            {"hooks.example.test": ["93.184.216.34"], "private.example.test": ["10.0.0.9"]}
        ),
    )
    with pytest.raises(DestinationBlocked):
        check_destination(url, allow_private=False)


def test_ssrf_guard_accepts_public_hosts_and_relaxes_in_development(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.connectors.network.socket.getaddrinfo",
        fake_resolver(
            {"hooks.example.test": ["93.184.216.34", "2606:2800:220:1:248:1893:25c8:1946"]}
        ),
    )
    check_destination("https://hooks.example.test/in", allow_private=False)
    check_destination("https://93.184.216.34/in", allow_private=False)
    check_destination("http://localhost:9/in", allow_private=True)
    monkeypatch.setattr(
        "app.connectors.network.get_settings", lambda: SimpleNamespace(environment="production")
    )
    with pytest.raises(DestinationBlocked):
        check_destination("http://localhost:9/in")
    with pytest.raises(ConnectorConfigError, match="config.url"):
        validate_with(WebhookConfig, {"url": "https://127.0.0.1/in"}, "config")


def test_webhook_config_rejects_reserved_headers() -> None:
    for headers in (
        {"X-OpsPilot-Signature": "forged"},
        {"Host": "evil.example"},
        {"Authorization": "Bearer leaked"},
        {"Proxy-Authorization": "Basic leaked"},
        {"Cookie": "session=leaked"},
        {"Bad Name": "x"},
        {"X-Ok": "line\nbreak"},
    ):
        with pytest.raises(ConnectorConfigError):
            validate_with(
                WebhookConfig, {"url": "http://localhost:9/in", "headers": headers}, "config"
            )
    assert validate_with(
        WebhookConfig,
        {"url": "http://localhost:9/in", "headers": {"X-Tenant": "northwind"}},
        "config",
    )["headers"] == {"X-Tenant": "northwind"}


def test_neutralize_cell_blocks_formulas_but_keeps_numbers() -> None:
    assert neutralize_cell("=SUM(A1)") == "'=SUM(A1)"
    assert neutralize_cell("@cmd") == "'@cmd"
    assert neutralize_cell("+cmd") == "'+cmd"
    assert neutralize_cell("-5.00") == "-5.00"
    assert neutralize_cell("+1") == "+1"
    assert neutralize_cell("-.5") == "-.5"
    assert neutralize_cell("") == ""
    assert neutralize_cell("Harbor") == "Harbor"


# Webhook


def signed_receiver(
    secret: str, status_code: int = 200, body: Any = None
) -> tuple[Any, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def handler(incoming: httpx.Request) -> httpx.Response:
        seen.append(incoming)
        timestamp = incoming.headers["X-OpsPilot-Timestamp"]
        expected = (
            "sha256="
            + hmac.new(
                secret.encode(), f"{timestamp}.{incoming.content.decode()}".encode(), hashlib.sha256
            ).hexdigest()
        )
        if not hmac.compare_digest(expected, incoming.headers["X-OpsPilot-Signature"]):
            return httpx.Response(401, json={"error": "bad signature"})
        if status_code >= 400:
            return httpx.Response(status_code, text="nope")
        return httpx.Response(status_code, json=body if body is not None else {"id": "evt_1"})

    return handler, seen


def webhook(handler: Any) -> WebhookConnector:
    return WebhookConnector(lambda: httpx.Client(transport=httpx.MockTransport(handler)))


def test_webhook_signs_requests_and_classifies_responses() -> None:
    secret = "shared-secret-value-1"
    config = {"url": "http://localhost:9/in", "headers": {"X-Tenant": "northwind"}}
    credentials = {"secret": secret}
    handler, seen = signed_receiver(secret)
    result = webhook(handler).execute(config, credentials, request(), "idem-key-1")
    assert result.ok and result.external_id == "evt_1" and not result.retryable
    assert result.response_summary.startswith("HTTP 200 (application/json,")
    sent = seen[0]
    assert sent.headers["X-OpsPilot-Idempotency-Key"] == "idem-key-1"
    assert sent.headers["X-Tenant"] == "northwind"
    assert sent.headers["Content-Type"] == "application/json"
    body = json.loads(sent.content)
    assert body == {
        "action_id": str(ACTION_ID),
        "document_id": str(DOCUMENT_ID),
        "action_type": "post_webhook",
        "payload": {"vendor": "Harbor Supply", "total": "110.00", "currency": "USD"},
        "proposed_at": "2026-09-27T10:30:00+00:00",
    }
    assert sent.content.decode() == canonical_body(body)

    wrong = webhook(handler).execute(config, {"secret": "another-secret-value"}, request(), "k")
    assert not wrong.ok and not wrong.retryable and wrong.response_summary.startswith("HTTP 401")
    for status_code, retryable in (
        (500, True),
        (429, True),
        (408, True),
        (400, False),
        (404, False),
    ):
        failing, _ = signed_receiver(secret, status_code)
        outcome = webhook(failing).execute(config, credentials, request(), "k")
        assert (outcome.ok, outcome.retryable) == (False, retryable), status_code

    def timeout(incoming: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=incoming)

    slow = webhook(timeout).execute(config, credentials, request(), "k")
    assert not slow.ok and slow.retryable and slow.response_summary == "Request timed out"
    missing = webhook(handler).execute(config, None, request(), "k")
    assert not missing.ok and not missing.retryable

    probe_handler, probe_seen = signed_receiver(secret)
    test = webhook(probe_handler).test_connection(config, credentials)
    assert test.ok and test.message == "HTTP 200"
    assert json.loads(probe_seen[0].content)["type"] == "test"
    preview = webhook(handler).preview(config, request())
    assert preview.kind == "post_webhook" and preview.after["payload"]["total"] == "110.00"
    assert "Harbor Supply" in " ".join(preview.lines)


def test_webhook_rechecks_destination_at_send_time(monkeypatch: pytest.MonkeyPatch) -> None:
    handler, seen = signed_receiver("shared-secret-value-1")

    def blocked(url: str, **kwargs: Any) -> None:
        raise DestinationBlocked("Destination resolves to a private or reserved address")

    monkeypatch.setattr("app.connectors.webhook.check_destination", blocked)
    result = webhook(handler).execute(
        {"url": "https://hooks.example.test/in"},
        {"secret": "shared-secret-value-1"},
        request(),
        "k",
    )
    assert not result.ok and not result.retryable and "private" in result.response_summary
    assert seen == []


# CSV export


def csv_connector(store: MemoryStore) -> CsvExportConnector:
    return CsvExportConnector(
        store_factory=lambda: store,
        lock=lambda org_id: nullcontext(),
        clock=lambda: datetime(2026, 9, 27, tzinfo=UTC),
    )


def test_csv_export_appends_idempotently_and_merges_headers() -> None:
    store = MemoryStore()
    connector = csv_connector(store)
    key = export_key(ORG_ID, CONNECTOR_ID, "2026-09")
    first = connector.execute(
        {"file_prefix": "ap"}, None, request(action_type="export_csv"), "key-1"
    )
    assert first.ok and first.external_id == key and not first.duplicate
    again = connector.execute(
        {"file_prefix": "ap"}, None, request(action_type="export_csv"), "key-1"
    )
    assert again.ok and again.duplicate and again.response_summary == "Row already exported"
    second = connector.execute(
        {"file_prefix": "ap"},
        None,
        request({"vendor": "=HYPERLINK()", "po": "PO-7"}, "export_csv"),
        "key-2",
    )
    assert second.ok
    lines = store.objects[key].decode().splitlines()
    assert lines[0] == f"{KEY_COLUMN},vendor,total,currency,po"
    assert lines[1] == "key-1,Harbor Supply,110.00,USD,"
    assert lines[2] == "key-2,'=HYPERLINK(),,,PO-7"
    assert len(lines) == 3
    assert month_of_key(key) == "2026-09" and month_of_key("exports/x/y.csv") is None
    preview = connector.preview({"file_prefix": "ap"}, request(action_type="export_csv"))
    assert preview.title == "Append a row to ap-2026-09.csv"
    assert connector.test_connection({}, None).ok
    store.fail = True
    down = connector.execute({}, None, request(action_type="export_csv"), "key-3")
    assert not down.ok and down.retryable
    assert not connector.test_connection({}, None).ok


# Google Sheets


def service_account() -> tuple[dict[str, str], Any]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    account = {
        "type": "service_account",
        "client_email": "bot@project.iam.gserviceaccount.com",
        "private_key": pem,
        "token_uri": "https://oauth2.googleapis.com/token",
    }
    return account, private_key.public_key()


class FakeSheets:
    def __init__(self, public_key: Any, column: list[list[str]], fail: int | None = None) -> None:
        self.public_key = public_key
        self.column = column
        self.fail = fail
        self.appended: list[dict[str, Any]] = []
        self.tokens = 0

    def handler(self, incoming: httpx.Request) -> httpx.Response:
        url = str(incoming.url)
        if url == "https://oauth2.googleapis.com/token":
            form = dict(pair.split("=", 1) for pair in incoming.content.decode().split("&"))
            assertion = httpx.QueryParams(f"a={form['assertion']}")["a"]
            claims = jwt.decode(
                assertion,
                self.public_key,
                algorithms=["RS256"],
                audience="https://oauth2.googleapis.com/token",
            )
            assert claims["iss"] == "bot@project.iam.gserviceaccount.com"
            assert claims["scope"].endswith("/auth/spreadsheets")
            self.tokens += 1
            return httpx.Response(200, json={"access_token": "ya29.token", "expires_in": 3600})
        assert incoming.headers["Authorization"] == "Bearer ya29.token"
        if self.fail is not None:
            return httpx.Response(self.fail, json={"error": {"message": "nope"}})
        if incoming.method == "GET" and url.endswith("/values/%27Ledger%27%21A%3AA"):
            return httpx.Response(200, json={"range": "Ledger!A:A", "values": self.column})
        if incoming.method == "GET" and "fields=sheets.properties.title" in url:
            return httpx.Response(200, json={"sheets": [{"properties": {"title": "Ledger"}}]})
        if incoming.method == "POST" and url.startswith(
            "https://sheets.googleapis.com/v4/spreadsheets/sheet_1234567890/values/%27Ledger%27%21A1:append"
        ):
            assert incoming.url.params["valueInputOption"] == "RAW"
            self.appended.append(json.loads(incoming.content))
            return httpx.Response(200, json={"updates": {"updatedRange": "Ledger!A2:D2"}})
        return httpx.Response(404, json={"error": "unexpected"})


def sheets(fake: FakeSheets) -> GoogleSheetsConnector:
    return GoogleSheetsConnector(lambda: httpx.Client(transport=httpx.MockTransport(fake.handler)))


def test_google_sheets_authenticates_with_rs256_and_appends_once() -> None:
    account, public_key = service_account()
    credentials = {"service_account_json": json.dumps(account)}
    GoogleSheetsCredentials.model_validate(credentials)
    config = {"spreadsheet_id": "sheet_1234567890", "sheet_name": "Ledger"}
    empty = FakeSheets(public_key, [])
    result = sheets(empty).execute(config, credentials, request(action_type="append_row"), "key-1")
    assert result.ok and result.external_id == "Ledger!A2:D2" and empty.tokens == 1
    assert empty.appended == [
        {
            "values": [
                [KEY_COLUMN, "vendor", "total", "currency"],
                ["key-1", "Harbor Supply", "110.00", "USD"],
            ]
        }
    ]
    populated = FakeSheets(public_key, [[KEY_COLUMN], ["key-1"]])
    duplicate = sheets(populated).execute(
        config, credentials, request(action_type="append_row"), "key-1"
    )
    assert duplicate.ok and duplicate.duplicate and populated.appended == []
    fresh = sheets(populated).execute(
        config, credentials, request(action_type="append_row"), "key-2"
    )
    assert fresh.ok and populated.appended[0]["values"] == [
        ["key-2", "Harbor Supply", "110.00", "USD"]
    ]
    forbidden = sheets(FakeSheets(public_key, [], fail=403)).execute(
        config, credentials, request(action_type="append_row"), "key-3"
    )
    assert not forbidden.ok and not forbidden.retryable and "HTTP 403" in forbidden.response_summary
    flaky = sheets(FakeSheets(public_key, [], fail=503)).execute(
        config, credentials, request(action_type="append_row"), "key-3"
    )
    assert not flaky.ok and flaky.retryable
    test = sheets(FakeSheets(public_key, [])).test_connection(config, credentials)
    assert test.ok and "Ledger" in test.message
    missing = sheets(FakeSheets(public_key, [])).test_connection(
        config | {"sheet_name": "Other"}, credentials
    )
    assert not missing.ok and "missing" in missing.message
    with pytest.raises(ConnectorConfigError, match="private_key"):
        validate_with(
            GoogleSheetsCredentials,
            {"service_account_json": json.dumps(account | {"private_key": "nope"})},
            "credentials",
        )


# Postgres table


def test_postgres_config_and_dsn_validation() -> None:
    assert PostgresTableConfig.model_validate(
        {"schema": "public", "table": "ap_ledger"}
    ).model_dump(mode="json") == {"schema": "public", "table": "ap_ledger"}
    with pytest.raises(ConnectorConfigError):
        validate_with(PostgresTableConfig, {"schema": "public; drop", "table": "t"}, "config")
    normalized = PostgresCredentials.model_validate(
        {"dsn": "postgresql+psycopg://u:p@db.example.test:5432/ledger"}
    )
    assert conninfo_to_dict(normalized.dsn) == {
        "host": "db.example.test",
        "port": "5432",
        "dbname": "ledger",
        "user": "u",
        "password": "p",
    }
    with pytest.raises(ConnectorConfigError, match="host"):
        validate_with(PostgresCredentials, {"dsn": "dbname=ledger user=u"}, "credentials")
    unreachable = PostgresTableConnector().execute(
        {"schema": "public", "table": "t"},
        {"dsn": "postgresql://u:p@127.0.0.1:1/ledger"},
        request(action_type="create_record"),
        "k",
    )
    assert not unreachable.ok and unreachable.retryable


@postgres
def test_postgres_table_inserts_once_under_scratch_schema() -> None:
    dsn = normalize_database_url(os.environ["DATABASE_OWNER_URL"]).replace(
        "postgresql+psycopg://", "postgresql://"
    )
    schema = f"scratch_{uuid.uuid4().hex[:8]}"
    connector = PostgresTableConnector()
    config = {"schema": schema, "table": "ap_ledger"}
    credentials = {"dsn": dsn}
    with psycopg.connect(dsn, autocommit=True) as connection:
        connection.execute(f"CREATE SCHEMA {schema}")
        connection.execute(f"CREATE TABLE {schema}.no_key (vendor text)")
    try:
        missing = connector.test_connection(config, credentials)
        assert not missing.ok and "not found" in missing.message
        no_key = connector.test_connection(config | {"table": "no_key"}, credentials)
        assert not no_key.ok and "opspilot_action_id" in no_key.message
        with psycopg.connect(dsn, autocommit=True) as connection:
            connection.execute(
                f"CREATE TABLE {schema}.ap_ledger (vendor text, total numeric(12,2), "
                "issued date, opspilot_action_id uuid UNIQUE)"
            )
        ready = connector.test_connection(config, credentials)
        assert ready.ok and "4 column(s)" in ready.message
        values = {"vendor": "Harbor Supply", "total": "110.00", "issued": "2026-09-05"}
        first = connector.execute(config, credentials, request(values, "create_record"), "k")
        assert first.ok and first.external_id == str(ACTION_ID) and not first.duplicate
        again = connector.execute(config, credentials, request(values, "create_record"), "k")
        assert again.ok and again.duplicate
        with psycopg.connect(dsn) as connection:
            rows = connection.execute(
                f"SELECT vendor, total, issued FROM {schema}.ap_ledger"
            ).fetchall()
        assert [(row[0], str(row[1]), row[2].isoformat()) for row in rows] == [
            ("Harbor Supply", "110.00", "2026-09-05")
        ]
        bad = connector.execute(
            config,
            credentials,
            request({"vendor": "x", "total": "not-a-number"}, "create_record"),
            "k2",
        )
        assert (
            not bad.ok
            and not bad.retryable
            and bad.response_summary == "InvalidTextRepresentation (22P02)"
            and "not-a-number" not in bad.response_summary
        )
        preview = connector.preview(config, request(values, "create_record"))
        assert preview.title == f"INSERT INTO {schema}.ap_ledger"
        assert preview.after["opspilot_action_id"] == str(ACTION_ID)
    finally:
        with psycopg.connect(dsn, autocommit=True) as connection:
            connection.execute(f"DROP SCHEMA {schema} CASCADE")


def test_registry_exposes_the_phase_3_catalogue() -> None:
    assert connector_types() == ["webhook", "csv_export", "postgres_table", "google_sheets"]
    assert connector_type_for("append_row") == "google_sheets"
    assert connector_type_for("create_record") == "postgres_table"
    assert connector_type_for("post_webhook") == "webhook"
    assert connector_type_for("export_csv") == "csv_export"
    assert connector_type_for("send_email") is None
    with pytest.raises(ConnectorConfigError):
        get_connector("browser")
    for name in connector_types():
        assert get_connector(name).describe_capabilities()["action_types"]


def test_webhook_pins_the_checked_address_and_keeps_the_hostname(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.connectors.network.get_settings", lambda: SimpleNamespace(environment="production")
    )
    monkeypatch.setattr(
        "app.connectors.network.socket.getaddrinfo",
        fake_resolver({"hooks.example.test": ["93.184.216.34"]}),
    )
    secret = "shared-secret-value-1"
    handler, seen = signed_receiver(secret)
    result = webhook(handler).execute(
        {"url": "https://hooks.example.test:8443/in?tenant=1"}, {"secret": secret}, request(), "k"
    )
    assert result.ok, result.response_summary
    sent = seen[0]
    # The connection goes to the address that passed the check; the name travels in the
    # Host header and the TLS extension, so verification and SNI still use the real name.
    assert sent.url.scheme == "https" and sent.url.host == "93.184.216.34"
    assert sent.url.port == 8443 and sent.url.path == "/in" and sent.url.query == b"tenant=1"
    assert sent.headers["Host"] == "hooks.example.test"
    assert sent.extensions["sni_hostname"] == "hooks.example.test"
    monkeypatch.setattr(
        "app.connectors.network.socket.getaddrinfo",
        fake_resolver({"hooks.example.test": ["2606:2800:220:1:248:1893:25c8:1946"]}),
    )
    six = check_destination("https://hooks.example.test/in")
    assert six.pinned_url == "https://[2606:2800:220:1:248:1893:25c8:1946]/in"
    assert six.hostname == "hooks.example.test"
    development = check_destination("http://localhost:9/in", allow_private=True)
    assert development.address is None and development.pinned_url == "http://localhost:9/in"
    with pytest.raises(DestinationBlocked, match="port"):
        check_destination("https://hooks.example.test:99999/in")


def test_postgres_dsn_guard_outside_development(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.connectors.network.get_settings", lambda: SimpleNamespace(environment="production")
    )
    monkeypatch.setattr(
        "app.connectors.network.socket.getaddrinfo",
        fake_resolver({"db.example.test": ["93.184.216.34"], "postgres": ["10.0.0.5"]}),
    )
    for dsn, fragment in (
        ("host=postgres dbname=ledger user=u password=p", "private"),
        ("host=/var/run/postgresql dbname=ledger user=u", "socket"),
        ("hostaddr=10.0.0.5 host=db.example.test dbname=ledger user=u", "hostaddr"),
        ("passfile=/etc/passwd host=db.example.test dbname=ledger user=u", "passfile"),
        ("host=db.example.test dbname=ledger user=u sslmode=disable", "sslmode"),
        ("host=db.example.test sslrootcert=/etc/ssl/x dbname=ledger user=u", "sslrootcert"),
        ("host=db.example.test options=-csearch_path=x dbname=ledger user=u", "options"),
        ("host=db.example.test,db2.example.test dbname=ledger user=u", "exactly one host"),
        ("host=localhost dbname=ledger user=u", "not publicly routable"),
        ("dbname=ledger user=u", "host"),
    ):
        with pytest.raises(ConnectorConfigError, match=fragment):
            validate_with(PostgresCredentials, {"dsn": dsn}, "credentials")
    accepted = validate_with(
        PostgresCredentials,
        {"dsn": "postgresql://u:p@db.example.test:5432/ledger"},
        "credentials",
    )
    parts = conninfo_to_dict(accepted["dsn"])
    assert parts["host"] == "db.example.test" and parts["sslmode"] == "require"
    assert "hostaddr" not in parts

    captured: dict[str, Any] = {}

    def fake_connect(conninfo: str, **kwargs: Any) -> None:
        captured.update(conninfo_to_dict(conninfo))
        captured["kwargs"] = kwargs
        raise psycopg.OperationalError("connection refused")

    monkeypatch.setattr("app.connectors.postgres_table.psycopg.connect", fake_connect)
    connector = PostgresTableConnector()
    config = {"schema": "public", "table": "ap_ledger"}
    result = connector.execute(config, accepted, request(action_type="create_record"), "k")
    assert not result.ok and result.retryable
    # Connect to the checked address, keep the name for certificate verification, force TLS.
    assert captured["hostaddr"] == "93.184.216.34" and captured["host"] == "db.example.test"
    assert captured["sslmode"] == "require" and captured["kwargs"]["connect_timeout"] == 5
    monkeypatch.setattr(
        "app.connectors.network.socket.getaddrinfo",
        fake_resolver({"db.example.test": ["10.0.0.9"]}),
    )
    captured.clear()
    flipped = connector.execute(config, accepted, request(action_type="create_record"), "k")
    assert not flipped.ok and not flipped.retryable and "private" in flipped.response_summary
    assert captured == {}
    assert not connector.test_connection(config, accepted).ok


def test_google_sheets_rejects_foreign_token_endpoints_and_partial_keys() -> None:
    account, _ = service_account()
    for changed, fragment in (
        ({"token_uri": "https://oauth2.example.test/token"}, "token_uri"),
        ({"token_uri": "http://oauth2.googleapis.com/token"}, "token_uri"),
        ({"client_email": None}, "client_email"),
        ({"private_key": None}, "private_key"),
    ):
        broken = {key: value for key, value in (account | changed).items() if value is not None}
        with pytest.raises(ConnectorConfigError, match=fragment):
            validate_with(
                GoogleSheetsCredentials, {"service_account_json": json.dumps(broken)}, "credentials"
            )
    without_uri = {key: value for key, value in account.items() if key != "token_uri"}
    GoogleSheetsCredentials.model_validate({"service_account_json": json.dumps(without_uri)})
