"""Email intake: parsing, the Mailpit and IMAP backends, inbox settings and the worker tick."""

import ipaddress
import json
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from email.message import EmailMessage as MimeMessage
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from scripts.generate_demo_invoice import invoice_pdf
from sqlalchemy import Engine, create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import email_intake, email_settings
from app.auth import current_session
from app.connectors.base import ConnectionTest, ConnectorConfigError
from app.connectors.credentials import decrypt_credentials
from app.connectors.network import DestinationBlocked
from app.db import SessionLocal, set_org_context
from app.email_intake import (
    MAX_BODY_CHARS,
    Attachment,
    ImapConfig,
    ImapSource,
    InboundMessage,
    MailpitSource,
    parse_email,
    poll_due_inboxes,
    validate_inbox_config,
    validate_inbox_credentials,
)
from app.intake_models import EmailInbox, EmailMessage
from app.main import app
from app.models import AuditEvent, Base, Document, Membership, Organization, User, WorkflowConfig
from app.workflow_config import default_invoice_config
from tests.conftest import TenantFactory, owner_engine, postgres
from tests.test_documents import MemoryStore

PDF = invoice_pdf(invoice_number="MAIL-0001")
AttachmentSpec = tuple[str, bytes, str, str]


def mime(
    sender: str = "Ada Vendor <vendor@example.com>",
    subject: str = "Invoice attached",
    body: str = "Hello\nsee attached",
    attachments: tuple[AttachmentSpec, ...] = (("invoice.pdf", PDF, "application", "pdf"),),
) -> bytes:
    message = MimeMessage()
    message["From"] = sender
    message["To"] = "acme@opspilot.local"
    message["Subject"] = subject
    message.set_content(body)
    for name, data, maintype, subtype in attachments:
        message.add_attachment(data, maintype=maintype, subtype=subtype, filename=name)
    return bytes(message)


def test_parse_email_reads_sender_subject_body_and_pdf_attachments() -> None:
    raw = mime(
        attachments=(
            ("invoice.pdf", PDF, "application", "pdf"),
            ("notes.txt", b"hi", "text", "plain"),
            ("scan.PDF", PDF, "application", "octet-stream"),
            ("fake.pdf", b"not a pdf", "application", "pdf"),
        )
    )
    message = parse_email(raw, "42")
    assert message.uid == "42"
    assert message.sender == "Ada Vendor <vendor@example.com>"
    assert message.subject == "Invoice attached" and message.body_text.startswith("Hello")
    assert [item.filename for item in message.attachments] == [
        "invoice.pdf",
        "notes.txt",
        "scan.PDF",
        "fake.pdf",
    ]
    assert [item.filename for item in message.pdf_attachments()] == ["invoice.pdf", "scan.PDF"]
    assert message.source_ref == "Ada Vendor <vendor@example.com> Invoice attached"
    long_body = parse_email(mime(body="x" * (MAX_BODY_CHARS + 500)), "1")
    assert len(long_body.body_text) == MAX_BODY_CHARS
    bare = parse_email(mime(sender="vendor@example.com", attachments=()), "2")
    assert bare.sender == "vendor@example.com" and bare.pdf_attachments() == []


def test_mailpit_source_fetches_unread_messages_and_marks_them_read() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/api/v1/search":
            assert request.url.params["query"] == 'to:"acme@opspilot.local" is:unread'
            assert request.url.params["limit"] == "25"
            return httpx.Response(
                200, json={"messages": [{"ID": "m1", "Read": False}, {"ID": "m2", "Read": False}]}
            )
        if request.url.path == "/api/v1/message/m1":
            return httpx.Response(
                200,
                json={
                    "ID": "m1",
                    "From": {"Name": "Ada", "Address": "ada@example.com"},
                    "Subject": "  Invoice\n 7 ",
                    "Text": "Body text",
                    "Attachments": [
                        {
                            "PartID": "2",
                            "FileName": "invoice.pdf",
                            "ContentType": "application/pdf",
                        },
                        {"PartID": "3", "FileName": "notes.txt", "ContentType": "text/plain"},
                    ],
                },
            )
        if request.url.path == "/api/v1/message/m1/part/2":
            return httpx.Response(200, content=PDF, headers={"Content-Type": "application/pdf"})
        if request.url.path == "/api/v1/message/m2":
            return httpx.Response(
                200,
                json={
                    "ID": "m2",
                    "From": {"Name": "", "Address": "b@example.com"},
                    "Subject": "No pdf",
                    "Text": "",
                    "Attachments": [
                        {"PartID": "2", "FileName": "photo.png", "ContentType": "image/png"}
                    ],
                },
            )
        if request.method == "PUT" and request.url.path == "/api/v1/messages":
            assert json.loads(request.content) == {"IDs": ["m1"], "Read": True}
            return httpx.Response(200, text="ok")
        if request.url.path == "/api/v1/info":
            return httpx.Response(200, json={"Version": "v1.31.2"})
        return httpx.Response(404)

    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://mailpit:8025")
    source = MailpitSource("http://mailpit:8025", "acme@opspilot.local", client)
    messages = source.fetch_new()
    assert [(m.uid, m.sender, m.subject, m.body_text) for m in messages] == [
        ("m1", "Ada <ada@example.com>", "Invoice 7", "Body text"),
        ("m2", "b@example.com", "No pdf", ""),
    ]
    assert [item.filename for item in messages[0].pdf_attachments()] == ["invoice.pdf"]
    assert messages[0].attachments[0].data == PDF and messages[1].attachments == []
    source.mark_processed("m1")
    assert source.test_connection() == ConnectionTest(
        True, "Mailpit v1.31.2 reachable; polling acme@opspilot.local"
    )
    assert calls == [
        "/api/v1/search",
        "/api/v1/message/m1",
        "/api/v1/message/m1/part/2",
        "/api/v1/message/m2",
        "/api/v1/messages",
        "/api/v1/info",
    ]
    source.close()


class FakeImap:
    """Records the IMAP conversation; answers UID SEARCH, FETCH and STORE like a server."""

    def __init__(self, raw: dict[str, bytes]) -> None:
        self.raw = raw
        self.calls: list[tuple[Any, ...]] = []
        self.connection: dict[str, Any] = {}
        self.logged_out = False

    def connect(self, **kwargs: Any) -> "FakeImap":
        self.connection = kwargs
        return self

    def login(self, user: str, password: str) -> tuple[str, list[bytes]]:
        self.calls.append(("login", user, password))
        return "OK", [b"ok"]

    def select(self, folder: str, readonly: bool = False) -> tuple[str, list[bytes]]:
        self.calls.append(("select", folder, readonly))
        return "OK", [b"2"]

    def uid(self, command: str, *args: Any) -> tuple[str, list[Any]]:
        self.calls.append(("uid", command, *args))
        if command == "SEARCH":
            return "OK", [" ".join(self.raw).encode("ascii")]
        if command == "FETCH":
            data = self.raw[str(args[0])]
            return "OK", [(f"{args[0]} (BODY[] {{{len(data)}}}".encode(), data), b")"]
        return "OK", [b""]

    def logout(self) -> tuple[str, list[bytes]]:
        self.logged_out = True
        return "BYE", [b""]


def test_imap_source_polls_unseen_with_uid_commands_and_pins_checked_hosts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeImap({"7": mime(subject="Seven"), "9": mime(subject="Nine", attachments=())})
    config = ImapConfig(
        host="Mail.Example.Test", username="ap@example.test", since=date(2026, 9, 1), folder="AP"
    )
    assert config.host == "mail.example.test" and config.port == 993
    source = ImapSource(config, "secret-pw", factory=fake.connect, allow_private=True)
    messages = source.fetch_new()
    assert fake.connection == {
        "host": "mail.example.test",
        "port": 993,
        "address": None,
        "timeout": 20,
    }
    assert [(m.uid, m.subject, len(m.pdf_attachments())) for m in messages] == [
        ("7", "Seven", 1),
        ("9", "Nine", 0),
    ]
    assert fake.calls[:2] == [("login", "ap@example.test", "secret-pw"), ("select", '"AP"', False)]
    assert ("uid", "SEARCH", None, "UNSEEN", "SINCE", "01-Sep-2026") in fake.calls
    assert ("uid", "FETCH", "7", "(BODY.PEEK[])") in fake.calls
    source.mark_processed("7")
    assert ("uid", "STORE", "7", "+FLAGS", "(\\Seen)") in fake.calls
    assert source.test_connection().ok
    source.close()
    assert fake.logged_out

    blocked = ImapSource(
        ImapConfig(host="localhost", username="x"), "pw", factory=fake.connect, allow_private=False
    )
    with pytest.raises(DestinationBlocked):
        blocked.fetch_new()
    pinned_to = ipaddress.ip_address("93.184.216.34")
    monkeypatch.setattr("app.email_intake.check_host", lambda host, allow_private=None: pinned_to)
    pinned = ImapSource(
        ImapConfig(host="mail.example.test", username="x"),
        "pw",
        factory=fake.connect,
        allow_private=False,
    )
    pinned.fetch_new()
    assert (
        fake.connection["address"] == pinned_to and fake.connection["host"] == "mail.example.test"
    )


def test_inbox_config_and_credential_validation() -> None:
    assert validate_inbox_config("mailpit", {}) == {}
    with pytest.raises(ConnectorConfigError, match="config"):
        validate_inbox_config("mailpit", {"host": "x"})
    assert validate_inbox_config("imap", {"host": "imap.example.test", "username": "ap"}) == {
        "host": "imap.example.test",
        "port": 993,
        "username": "ap",
        "folder": "INBOX",
        "since": None,
    }
    with pytest.raises(ConnectorConfigError, match="config.host"):
        validate_inbox_config("imap", {"host": "bad host!", "username": "ap"})
    with pytest.raises(ConnectorConfigError, match="config.folder"):
        validate_inbox_config(
            "imap", {"host": "imap.example.test", "username": "ap", "folder": 'A"'}
        )
    with pytest.raises(ConnectorConfigError, match="config.port"):
        validate_inbox_config(
            "imap", {"host": "imap.example.test", "username": "ap", "port": 70000}
        )
    with pytest.raises(ConnectorConfigError, match="credentials.password"):
        validate_inbox_credentials("imap", None)
    assert validate_inbox_credentials("imap", {"password": "pw"}) == {"password": "pw"}
    with pytest.raises(ConnectorConfigError, match="no credentials"):
        validate_inbox_credentials("mailpit", {"password": "x"})
    assert validate_inbox_credentials("mailpit", None) == {}


@dataclass
class Inbox:
    client: TestClient
    engine: Engine
    actors: dict[str, uuid.UUID]
    org_id: uuid.UUID
    actor: str = "admin"

    def audits(self, event_type: str) -> list[dict[str, Any]]:
        with Session(self.engine) as session:
            rows = session.scalars(
                select(AuditEvent).where(
                    AuditEvent.org_id == self.org_id, AuditEvent.event_type == event_type
                )
            )
            return [json.loads(row.detail_json) for row in rows]


@pytest.fixture
def inbox(monkeypatch: pytest.MonkeyPatch) -> Iterator[Inbox]:
    monkeypatch.setattr(
        email_settings,
        "get_settings",
        lambda: SimpleNamespace(environment="development", mailpit_api_url="http://mailpit:8025"),
    )
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    org_id, other_org = uuid.uuid4(), uuid.uuid4()
    actors = {name: uuid.uuid4() for name in ("admin", "viewer", "external")}
    with Session(engine) as session:
        session.add_all(
            [
                Organization(id=org_id, slug="acme", name="Acme"),
                Organization(id=other_org, slug="elsewhere", name="Elsewhere"),
            ]
        )
        for name, user_id in actors.items():
            session.add(User(id=user_id, email=f"{name}@example.com", password_hash="unused"))
        session.flush()
        for name, user_id in actors.items():
            session.add(
                Membership(
                    org_id=other_org if name == "external" else org_id,
                    user_id=user_id,
                    role="admin" if name == "external" else name,
                    status="active",
                )
            )
        for target in (org_id, other_org):
            session.add(
                WorkflowConfig(
                    org_id=target, version=1, config_json=default_invoice_config().model_dump_json()
                )
            )
        session.commit()
    with TestClient(app) as client:
        state = Inbox(client, engine, actors, org_id)

        def context() -> Iterator[tuple[Session, User, Organization, Membership]]:
            with Session(engine, expire_on_commit=False) as session:
                user = session.get(User, actors[state.actor])
                assert user is not None
                membership = session.scalar(select(Membership).where(Membership.user_id == user.id))
                assert membership is not None
                org = session.get(Organization, membership.org_id)
                assert org is not None
                yield session, user, org, membership

        app.dependency_overrides[current_session] = context
        try:
            yield state
        finally:
            app.dependency_overrides.pop(current_session, None)
    engine.dispose()


def test_inbox_settings_lifecycle_and_connection_test(
    inbox: Inbox, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = inbox.client
    path = "/v1/settings/email-inbox"
    assert client.get(path).json() is None
    created = client.post(path, json={"version": 0, "backend": "mailpit"})
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["address"] == "acme@opspilot.local" and body["backend"] == "mailpit"
    assert body["has_credentials"] is False and body["active"] is True and body["version"] == 1
    assert body["messages_processed"] == 0 and body["poll_interval_seconds"] == 60
    assert body["next_poll_at"] is None and body["last_error"] is None
    assert client.get(path).json()["address"] == "acme@opspilot.local"
    assert client.post(path, json={"version": 0, "backend": "mailpit"}).status_code == 409

    imap = {
        "backend": "imap",
        "address": "AP@Example.test",
        "config": {"host": "imap.example.test", "username": "ap"},
    }
    missing = client.post(path, json={"version": 1, **imap})
    assert (
        missing.status_code == 422 and "credentials.password" in missing.json()["error"]["message"]
    )
    saved = client.post(path, json={"version": 1, **imap, "credentials": {"password": "pw-1"}})
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["backend"] == "imap" and body["address"] == "ap@example.test"
    assert body["has_credentials"] is True and body["version"] == 2 and "credentials" not in body
    assert body["config"] == {
        "host": "imap.example.test",
        "port": 993,
        "username": "ap",
        "folder": "INBOX",
        "since": None,
    }
    with Session(inbox.engine) as session:
        row = session.get(EmailInbox, inbox.org_id)
        assert row is not None and row.credentials_encrypted is not None
        assert decrypt_credentials(row.credentials_encrypted) == {"password": "pw-1"}
        assert row.credentials_encrypted != "pw-1" and "pw-1" not in row.credentials_encrypted

    kept = client.post(
        path,
        json={
            "version": 2,
            **imap,
            "config": {"host": "imap.example.test", "username": "ap", "folder": "AP"},
            "active": False,
        },
    )
    assert kept.status_code == 200, kept.text
    assert kept.json()["has_credentials"] is True and kept.json()["active"] is False
    assert kept.json()["version"] == 3 and kept.json()["config"]["folder"] == "AP"
    bad_host = client.post(
        path, json={"version": 3, **imap, "config": {"host": "not a host", "username": "ap"}}
    )
    assert bad_host.status_code == 422 and "config.host" in bad_host.json()["error"]["message"]
    no_address = client.post(path, json={"version": 3, **imap, "address": "nope"})
    assert no_address.status_code == 422

    monkeypatch.setattr(
        email_intake,
        "test_inbox_connection",
        lambda snapshot: ConnectionTest(True, f"ok {snapshot.backend} {snapshot.address}"),
    )
    tested = client.post(f"{path}/test")
    assert tested.status_code == 200, tested.text
    assert tested.json()["ok"] is True and tested.json()["message"] == "ok imap ap@example.test"
    current = client.get(path).json()
    assert (
        current["last_test_ok"] is True
        and current["last_test_message"] == "ok imap ap@example.test"
    )
    assert current["last_test_at"] is not None
    assert [event["backend"] for event in inbox.audits("email_inbox.created")] == ["mailpit"]
    assert len(inbox.audits("email_inbox.updated")) == 2
    assert inbox.audits("email_inbox.tested") == [
        {"ok": True, "message": "ok imap ap@example.test"}
    ]

    inbox.actor = "viewer"
    assert client.get(path).status_code == 403
    assert client.post(path, json={"version": 3, "backend": "mailpit"}).status_code == 403
    assert client.post(f"{path}/test").status_code == 403
    inbox.actor = "external"
    assert client.get(path).json() is None
    assert client.post(f"{path}/test").status_code == 409

    monkeypatch.setattr(
        email_settings,
        "get_settings",
        lambda: SimpleNamespace(environment="production", mailpit_api_url=None),
    )
    refused = client.post(path, json={"version": 0, "backend": "mailpit"})
    assert refused.status_code == 422 and "development" in refused.json()["error"]["message"]


@dataclass
class FakeSource:
    messages: list[InboundMessage]
    marked: list[str] = field(default_factory=list)
    fail: bool = False

    def fetch_new(self) -> list[InboundMessage]:
        if self.fail:
            raise httpx.ConnectError("down")
        return list(self.messages)

    def mark_processed(self, uid: str) -> None:
        self.marked.append(uid)

    def test_connection(self) -> ConnectionTest:
        return ConnectionTest(True, "ok")

    def close(self) -> None:
        return None


def _reset_timer(org_id: uuid.UUID) -> None:
    engine = owner_engine()
    try:
        with Session(engine) as session, session.begin():
            row = session.get(EmailInbox, org_id)
            assert row is not None
            row.next_poll_at = None
    finally:
        engine.dispose()


@postgres
def test_worker_tick_polls_due_inboxes_once_and_is_idempotent(
    make_tenant: TenantFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant, idle = make_tenant(), make_tenant()
    engine = owner_engine()
    with Session(engine) as session, session.begin():
        for target, active in ((tenant, True), (idle, False)):
            session.add(
                EmailInbox(
                    org_id=target.org_id,
                    backend="mailpit",
                    address=f"{target.slug}@opspilot.local",
                    config_json="{}",
                    active=active,
                    version=1,
                    created_by=target.users["admin"],
                )
            )
    engine.dispose()
    source = FakeSource(
        [
            InboundMessage(
                "m1",
                "Ada <ada@example.com>",
                "Invoice 7",
                "Body\ntext",
                [Attachment("invoice.pdf", PDF, "application/pdf")],
            ),
            InboundMessage("m2", "b@example.com", "No attachment", "", []),
        ]
    )
    monkeypatch.setattr(email_intake, "build_source", lambda snapshot, allow_private=None: source)
    store = MemoryStore()
    started = datetime.now(UTC)
    # Scoped to these two organizations so inboxes of other tenants in the shared
    # database do not count.
    scope = [tenant.org_id, idle.org_id]
    assert poll_due_inboxes(store=store, org_ids=scope) == 1

    with SessionLocal() as session:
        set_org_context(session, tenant.org_id)
        documents = session.scalars(select(Document).where(Document.org_id == tenant.org_id)).all()
        assert len(documents) == 1
        document = documents[0]
        assert document.source == "email" and document.status == "queued"
        assert document.source_ref == "Ada <ada@example.com> Invoice 7"
        assert document.context_text == "Body\ntext"
        assert document.uploaded_by == tenant.users["admin"]
        rows = {row.uid: row for row in session.scalars(select(EmailMessage))}
        assert rows["m1"].document_id == document.id and rows["m1"].document_count == 1
        assert rows["m1"].error is None and rows["m1"].sender == "Ada <ada@example.com>"
        assert rows["m2"].document_id is None and rows["m2"].error == "No PDF attachment"
        row = session.get(EmailInbox, tenant.org_id)
        assert row is not None and row.last_polled_at is not None and row.last_error is None
        assert row.next_poll_at is not None and row.next_poll_at > started
        received = session.scalar(
            select(AuditEvent).where(
                AuditEvent.org_id == tenant.org_id,
                AuditEvent.document_id == document.id,
                AuditEvent.event_type == "document.received",
            )
        )
        assert received is not None and received.actor_user_id is None
        assert json.loads(received.detail_json)["message_uid"] == "m1"
        assert json.loads(received.detail_json)["source"] == "email"
    assert source.marked == ["m1", "m2"]

    # Not due again yet; an inactive inbox is never polled.
    assert poll_due_inboxes(store=store, org_ids=scope) == 0
    with SessionLocal() as session:
        set_org_context(session, idle.org_id)
        idle_row = session.get(EmailInbox, idle.org_id)
        assert idle_row is not None and idle_row.last_polled_at is None

    # The same messages again create nothing new.
    _reset_timer(tenant.org_id)
    assert poll_due_inboxes(store=store, org_ids=scope) == 1
    with SessionLocal() as session:
        set_org_context(session, tenant.org_id)
        assert len(session.scalars(select(Document)).all()) == 1
        assert len(session.scalars(select(EmailMessage)).all()) == 2
    assert source.marked == ["m1", "m2", "m1", "m2"]

    # A failing mailbox records the error and keeps the inbox for the next tick.
    source.fail = True
    _reset_timer(tenant.org_id)
    assert poll_due_inboxes(store=store, org_ids=scope) == 1
    with SessionLocal() as session:
        set_org_context(session, tenant.org_id)
        row = session.get(EmailInbox, tenant.org_id)
        assert row is not None and row.last_error == "Mailpit request failed: ConnectError"
