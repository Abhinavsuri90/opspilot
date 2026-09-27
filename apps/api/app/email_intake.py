"""Email intake: poll one mailbox per organization and turn PDF attachments into documents.

Two backends implement :class:`EmailSource`. ``imap`` talks IMAP over TLS to a customer
mailbox with a Fernet-encrypted password; outside development the host must pass the same
address guard as webhook destinations and the connection is pinned to the checked address.
``mailpit`` reads the local Mailpit HTTP API in development, where every organization owns
``<slug>@opspilot.local``. Polling is idempotent: a processed message uid is recorded in
``email_messages`` and re-created documents are caught by the content hash.
"""

from __future__ import annotations

import email
import email.policy
import imaplib
import logging
import re
import socket
import ssl
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from email.message import EmailMessage as ParsedEmail
from email.utils import formataddr, parseaddr
from typing import Any, Protocol

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy import select

from app import document_service
from app.config import get_settings
from app.connectors.base import ConnectionTest, ConnectorConfigError, CredentialsUnavailable
from app.connectors.credentials import decrypt_credentials
from app.connectors.network import Address, DestinationBlocked, check_host
from app.db import SessionLocal, set_org_context
from app.document_service import (
    DocumentAccessDenied,
    DocumentLimitReached,
    InvalidDocument,
    MissingWorkflowConfig,
)
from app.intake_models import EmailInbox, EmailMessage
from app.limits import MAX_UPLOAD_BYTES
from app.models import Organization
from app.repositories import get_email_inbox, get_email_message
from app.storage import ObjectStore, StorageError, get_store
from app.timeouts import OperationTimeout, ParserBusy, run_connector_call

logger = logging.getLogger(__name__)
POLL_INTERVAL_SECONDS = 60
POLL_TIMEOUT_SECONDS = 30.0
MAX_MESSAGES_PER_POLL = 25
MAX_BODY_CHARS = document_service.MAX_CONTEXT_CHARS
MAILPIT_DOMAIN = "opspilot.local"
IMAP_TIMEOUT_SECONDS = 20
_HOSTNAME = r"^(?=.{1,253}$)(?!-)[A-Za-z0-9-]{1,63}(?<!-)(\.(?!-)[A-Za-z0-9-]{1,63}(?<!-))*$"


@dataclass(frozen=True)
class Attachment:
    filename: str
    data: bytes
    content_type: str

    @property
    def is_pdf(self) -> bool:
        return (
            self.content_type.lower() == "application/pdf" or self.filename.lower().endswith(".pdf")
        ) and self.data.startswith(b"%PDF-")


@dataclass(frozen=True)
class InboundMessage:
    uid: str
    sender: str
    subject: str
    body_text: str
    attachments: list[Attachment] = field(default_factory=list)

    def pdf_attachments(self) -> list[Attachment]:
        return [item for item in self.attachments if item.is_pdf]

    @property
    def source_ref(self) -> str:
        return f"{self.sender} {self.subject}".strip()[: document_service.MAX_SOURCE_REF_CHARS]


class EmailSource(Protocol):
    def fetch_new(self) -> list[InboundMessage]: ...

    def mark_processed(self, uid: str) -> None: ...

    def test_connection(self) -> ConnectionTest: ...

    def close(self) -> None: ...


# Configuration models


class ImapConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    host: str = Field(min_length=1, max_length=253)
    port: int = Field(default=993, ge=1, le=65535)
    username: str = Field(min_length=1, max_length=320)
    folder: str = Field(default="INBOX", min_length=1, max_length=200)
    # Only messages dated on or after this day are considered (IMAP SINCE).
    since: date | None = None

    @field_validator("host")
    @classmethod
    def lowercase_host(cls, value: str) -> str:
        host = value.strip().lower()
        if re.fullmatch(_HOSTNAME, host) is None:
            raise ValueError("must be a host name such as imap.example.com")
        return host

    @field_validator("folder")
    @classmethod
    def plain_folder(cls, value: str) -> str:
        if any(ord(char) < 32 or char in '"\\' for char in value):
            raise ValueError("Folder name contains characters IMAP cannot quote")
        return value


class ImapCredentials(BaseModel):
    model_config = ConfigDict(extra="forbid")

    password: str = Field(min_length=1, max_length=1024)


class MailpitConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")


def mailpit_address(slug: str) -> str:
    return f"{slug}@{MAILPIT_DOMAIN}"


# Message parsing shared by the IMAP backend and the test-email script


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit]


def parse_email(raw: bytes, uid: str) -> InboundMessage:
    """Sender, subject, plain-text body (bounded) and attachments from an RFC 822 message."""
    parsed = email.message_from_bytes(raw, policy=email.policy.default)
    assert isinstance(parsed, ParsedEmail)
    name, address = parseaddr(str(parsed.get("From", "")))
    sender = formataddr((name, address)) if address else str(parsed.get("From", "")).strip()
    subject = " ".join(str(parsed.get("Subject", "")).split())
    body = ""
    plain = parsed.get_body(preferencelist=("plain",))
    if plain is not None:
        try:
            body = str(plain.get_content())
        except (LookupError, UnicodeDecodeError, KeyError):
            body = ""
    attachments: list[Attachment] = []
    for part in parsed.iter_attachments():
        payload = part.get_payload(decode=True)
        if not isinstance(payload, bytes) or len(payload) > MAX_UPLOAD_BYTES:
            continue
        attachments.append(
            Attachment(part.get_filename() or "attachment", payload, part.get_content_type())
        )
    return InboundMessage(
        uid, sender[:320], subject[:300], _clip(body, MAX_BODY_CHARS), attachments
    )


# Backends


class MailpitSource:
    """Development backend over Mailpit's HTTP API (verified against Mailpit v1.31)."""

    def __init__(self, base_url: str, address: str, client: httpx.Client | None = None) -> None:
        self.address = address
        self.client = client or httpx.Client(base_url=base_url, timeout=10)

    def fetch_new(self) -> list[InboundMessage]:
        response = self.client.get(
            "/api/v1/search",
            params={"query": f'to:"{self.address}" is:unread', "limit": MAX_MESSAGES_PER_POLL},
        )
        response.raise_for_status()
        rows = response.json().get("messages") or []
        messages = []
        for row in rows:
            message_id = str(row.get("ID", ""))
            if not message_id:
                continue
            detail = self.client.get(f"/api/v1/message/{message_id}")
            detail.raise_for_status()
            body = detail.json()
            sender_info = body.get("From") or {}
            sender = formataddr(
                (str(sender_info.get("Name") or ""), str(sender_info.get("Address") or ""))
            )
            attachments = []
            for item in body.get("Attachments") or []:
                content_type = str(item.get("ContentType") or "")
                filename = str(item.get("FileName") or "attachment")
                if content_type.lower() != "application/pdf" and not filename.lower().endswith(
                    ".pdf"
                ):
                    continue
                part = self.client.get(f"/api/v1/message/{message_id}/part/{item.get('PartID')}")
                part.raise_for_status()
                if len(part.content) <= MAX_UPLOAD_BYTES:
                    attachments.append(Attachment(filename, part.content, content_type))
            messages.append(
                InboundMessage(
                    message_id,
                    sender[:320],
                    " ".join(str(body.get("Subject") or "").split())[:300],
                    _clip(str(body.get("Text") or ""), MAX_BODY_CHARS),
                    attachments,
                )
            )
        return messages

    def mark_processed(self, uid: str) -> None:
        response = self.client.put("/api/v1/messages", json={"IDs": [uid], "Read": True})
        response.raise_for_status()

    def test_connection(self) -> ConnectionTest:
        response = self.client.get("/api/v1/info")
        response.raise_for_status()
        version = response.json().get("Version", "unknown")
        return ConnectionTest(True, f"Mailpit {version} reachable; polling {self.address}")

    def close(self) -> None:
        self.client.close()


class PinnedIMAP4SSL(imaplib.IMAP4_SSL):
    """IMAP over TLS that connects to a pre-checked address while verifying the host name.

    ``address`` is the result of the destination guard. Connecting to it (rather than
    resolving the name again) closes the DNS-rebinding window; TLS still verifies the
    certificate against ``host`` because that is what SNI and hostname checking use.
    """

    def __init__(
        self, host: str, port: int, address: Address | None, timeout: float | None = None
    ) -> None:
        self.pinned_address = str(address) if address is not None else None
        context = ssl.create_default_context()
        super().__init__(host, port, ssl_context=context, timeout=timeout)

    def _create_socket(self, timeout: float | None = None) -> ssl.SSLSocket:
        target = self.pinned_address or self.host
        sock = socket.create_connection((target, self.port), timeout)
        wrapped: ssl.SSLSocket = self.ssl_context.wrap_socket(sock, server_hostname=self.host)
        return wrapped


ImapFactory = Callable[..., Any]


class ImapSource:
    """Customer mailbox over IMAP; the ``factory`` is injectable so tests use a fake."""

    def __init__(
        self,
        config: ImapConfig,
        password: str,
        *,
        factory: ImapFactory | None = None,
        allow_private: bool | None = None,
    ) -> None:
        self.config = config
        self._password = password
        self._factory = factory or PinnedIMAP4SSL
        self._allow_private = allow_private
        self._client: Any | None = None

    def _connect(self) -> Any:
        if self._client is not None:
            return self._client
        address = check_host(self.config.host, allow_private=self._allow_private)
        client = self._factory(
            host=self.config.host,
            port=self.config.port,
            address=address,
            timeout=IMAP_TIMEOUT_SECONDS,
        )
        client.login(self.config.username, self._password)
        status, _ = client.select(f'"{self.config.folder}"', readonly=False)
        if status != "OK":
            raise ConnectorConfigError(f"IMAP folder {self.config.folder!r} could not be opened")
        self._client = client
        return client

    def _search(self, client: Any) -> list[str]:
        criteria: list[str] = ["UNSEEN"]
        if self.config.since is not None:
            criteria += ["SINCE", self.config.since.strftime("%d-%b-%Y")]
        status, data = client.uid("SEARCH", None, *criteria)
        if status != "OK":
            raise ConnectorConfigError("IMAP search failed")
        raw = data[0] if data else b""
        text = raw.decode("ascii", "ignore") if isinstance(raw, bytes) else str(raw or "")
        return text.split()

    def fetch_new(self) -> list[InboundMessage]:
        client = self._connect()
        messages = []
        for uid in self._search(client)[:MAX_MESSAGES_PER_POLL]:
            status, data = client.uid("FETCH", uid, "(BODY.PEEK[])")
            if status != "OK":
                continue
            raw = next(
                (
                    item[1]
                    for item in data
                    if isinstance(item, tuple) and len(item) > 1 and isinstance(item[1], bytes)
                ),
                None,
            )
            if raw is None:
                continue
            messages.append(parse_email(raw, uid))
        return messages

    def mark_processed(self, uid: str) -> None:
        client = self._connect()
        client.uid("STORE", uid, "+FLAGS", "(\\Seen)")

    def test_connection(self) -> ConnectionTest:
        client = self._connect()
        status, data = client.uid("SEARCH", None, "ALL")
        count = len((data[0] or b"").split()) if status == "OK" and data else 0
        return ConnectionTest(
            True, f"Connected to {self.config.host}; {count} message(s) in {self.config.folder}"
        )

    def close(self) -> None:
        client, self._client = self._client, None
        if client is None:
            return
        try:
            client.logout()
        except Exception:  # a failed logout does not matter once the poll finished
            logger.debug("IMAP logout failed", exc_info=True)


# Building a source from the stored inbox row


@dataclass(frozen=True)
class InboxSnapshot:
    """Everything a poll needs, copied out of the row so no transaction stays open."""

    org_id: uuid.UUID
    slug: str
    backend: str
    address: str
    config: dict[str, Any]
    credentials_encrypted: str | None
    created_by: uuid.UUID


def validate_inbox_config(backend: str, config: dict[str, Any]) -> dict[str, Any]:
    model: type[BaseModel] = ImapConfig if backend == "imap" else MailpitConfig
    try:
        return model.model_validate(config).model_dump(mode="json")
    except ValidationError as exc:
        first = exc.errors()[0]
        location = ".".join(str(part) for part in first["loc"])
        raise ConnectorConfigError(f"config.{location}: {first['msg']}".rstrip(". ")) from exc


def validate_inbox_credentials(backend: str, credentials: dict[str, Any] | None) -> dict[str, Any]:
    if backend != "imap":
        if credentials:
            raise ConnectorConfigError("The Mailpit backend takes no credentials")
        return {}
    try:
        return ImapCredentials.model_validate(credentials or {}).model_dump()
    except ValidationError as exc:
        raise ConnectorConfigError(f"credentials.{exc.errors()[0]['loc'][0]}: required") from exc


def build_source(snapshot: InboxSnapshot, *, allow_private: bool | None = None) -> EmailSource:
    if snapshot.backend == "mailpit":
        base_url = get_settings().mailpit_api_url
        if not base_url:
            raise ConnectorConfigError("MAILPIT_API_URL is not configured on this deployment")
        return MailpitSource(base_url, snapshot.address)
    if snapshot.backend == "imap":
        if snapshot.credentials_encrypted is None:
            raise CredentialsUnavailable("The IMAP inbox has no stored password")
        credentials = decrypt_credentials(snapshot.credentials_encrypted)
        return ImapSource(
            ImapConfig.model_validate(snapshot.config),
            str(credentials.get("password", "")),
            allow_private=allow_private,
        )
    raise ConnectorConfigError(f"Unknown email backend: {snapshot.backend}")


def snapshot_of(inbox: EmailInbox, slug: str) -> InboxSnapshot:
    import json

    try:
        config = json.loads(inbox.config_json)
    except ValueError:
        config = {}
    return InboxSnapshot(
        org_id=inbox.org_id,
        slug=slug,
        backend=inbox.backend,
        address=inbox.address,
        config=config if isinstance(config, dict) else {},
        credentials_encrypted=inbox.credentials_encrypted,
        created_by=inbox.created_by,
    )


def _problem(exc: BaseException) -> str:
    """Error text safe to store: class and message, never mailbox content."""
    if isinstance(exc, OperationTimeout):
        return "Mailbox poll timed out"
    if isinstance(exc, ParserBusy):
        return "Worker is busy; the inbox is retried next tick"
    if isinstance(exc, DestinationBlocked | ConnectorConfigError | CredentialsUnavailable):
        return str(exc)[:300]
    if isinstance(exc, httpx.HTTPError):
        return f"Mailpit request failed: {type(exc).__name__}"[:300]
    if isinstance(exc, imaplib.IMAP4.error):
        return "IMAP server rejected the request"
    if isinstance(exc, OSError | ssl.SSLError):
        return f"Mailbox connection failed: {type(exc).__name__}"[:300]
    return f"{type(exc).__name__}"[:300]


# Polling


@dataclass
class PollOutcome:
    messages: int = 0
    documents: int = 0
    skipped: int = 0
    error: str | None = None


def process_message(
    snapshot: InboxSnapshot, message: InboundMessage, store: ObjectStore
) -> tuple[int, str | None] | None:
    """Create documents for one message; None when the uid was processed earlier.

    Each PDF becomes a document through the normal upload path (hash de-duplication, quota,
    outbox event). The message row is written last, so a crash before it is retried and the
    retry finds the documents already there.
    """
    org_id = snapshot.org_id
    with SessionLocal() as session:
        set_org_context(session, org_id)
        if get_email_message(session, org_id, message.uid) is not None:
            return None
    linked: list[uuid.UUID] = []
    created = 0
    problems: list[str] = []
    for attachment in message.pdf_attachments():
        with SessionLocal() as session:
            set_org_context(session, org_id)
            try:
                result = document_service.upload(
                    session,
                    store,
                    org_id,
                    snapshot.created_by,
                    attachment.filename,
                    attachment.data,
                    "admin",
                    source="email",
                    source_ref=message.source_ref,
                    context_text=message.body_text,
                    audit_actor=None,
                    audit_detail={"message_uid": message.uid, "inbox": snapshot.address},
                )
            except (InvalidDocument, DocumentLimitReached, MissingWorkflowConfig) as exc:
                problems.append(f"{attachment.filename}: {exc}")
                continue
            except DocumentAccessDenied:
                problems.append(f"{attachment.filename}: duplicate of a restricted document")
                continue
            linked.append(result.id)
            if not result.duplicate:
                created += 1
    if not message.pdf_attachments():
        problems.append("No PDF attachment")
    error = "; ".join(problems)[:300] if problems else None
    with SessionLocal() as session, session.begin():
        set_org_context(session, org_id)
        session.add(
            EmailMessage(
                id=uuid.uuid4(),
                org_id=org_id,
                uid=message.uid[:255],
                sender=message.sender[:320],
                subject=message.subject[:300],
                # The first document the message points at, even when the PDF was already
                # known; document_count only counts documents this message created.
                document_id=linked[0] if linked else None,
                document_count=created,
                error=error,
                processed_at=datetime.now(UTC),
            )
        )
    return created, error


def poll_inbox(
    snapshot: InboxSnapshot,
    store: ObjectStore | None = None,
    *,
    source: EmailSource | None = None,
) -> PollOutcome:
    """Fetch new messages under a hard timeout, create documents, then mark each message."""
    outcome = PollOutcome()
    object_store = store or get_store()
    opened = source
    try:
        opened = opened or build_source(snapshot)
        messages = run_connector_call(opened.fetch_new, POLL_TIMEOUT_SECONDS)
        for message in messages[:MAX_MESSAGES_PER_POLL]:
            result = process_message(snapshot, message, object_store)
            if result is None:
                outcome.skipped += 1
            else:
                outcome.messages += 1
                outcome.documents += result[0]
            opened.mark_processed(message.uid)
    except StorageError as exc:
        # Transient: nothing was recorded for the failing message, so it is retried.
        outcome.error = str(exc)[:300]
    except Exception as exc:
        outcome.error = _problem(exc)
        logger.warning("Email poll failed for inbox %s: %s", snapshot.address, outcome.error)
    finally:
        if opened is not None:
            opened.close()
    return outcome


def claim_due_inbox(org_id: uuid.UUID, now: datetime) -> InboxSnapshot | None:
    """Lease the organization's inbox if it is active and due; sets the next poll time."""
    with SessionLocal() as session, session.begin():
        set_org_context(session, org_id)
        inbox = get_email_inbox(session, org_id, lock=True)
        if inbox is None or not inbox.active:
            return None
        if inbox.next_poll_at is not None and _aware(inbox.next_poll_at) > now:
            return None
        inbox.next_poll_at = now + timedelta(seconds=POLL_INTERVAL_SECONDS)
        org = session.get(Organization, org_id)
        return snapshot_of(inbox, org.slug if org is not None else "")


def record_poll(org_id: uuid.UUID, outcome: PollOutcome, now: datetime) -> None:
    with SessionLocal() as session, session.begin():
        set_org_context(session, org_id)
        inbox = get_email_inbox(session, org_id)
        if inbox is None:
            return
        inbox.last_polled_at = now
        inbox.last_error = outcome.error


def poll_due_inboxes(
    now: datetime | None = None,
    store: ObjectStore | None = None,
    *,
    org_ids: Iterable[uuid.UUID] | None = None,
) -> int:
    """One tick: poll every active inbox whose next poll time has passed. Returns polls made.

    ``org_ids`` limits the tick to some organizations; the worker leaves it unset.
    """
    now = now or datetime.now(UTC)
    if org_ids is None:
        with SessionLocal() as session:
            org_ids = list(session.scalars(select(Organization.id).order_by(Organization.id)))
    polled = 0
    for org_id in org_ids:
        snapshot = claim_due_inbox(org_id, now)
        if snapshot is None:
            continue
        outcome = poll_inbox(snapshot, store)
        record_poll(org_id, outcome, datetime.now(UTC))
        polled += 1
        if outcome.messages or outcome.error:
            logger.info(
                "Polled inbox for org %s: %d message(s), %d document(s), error=%s",
                org_id,
                outcome.messages,
                outcome.documents,
                outcome.error,
            )
    return polled


def test_inbox_connection(snapshot: InboxSnapshot) -> ConnectionTest:
    """An administrator probe of the mailbox; connects and counts, never processes."""
    source: EmailSource | None = None
    try:
        source = build_source(snapshot)
        return run_connector_call(source.test_connection, POLL_TIMEOUT_SECONDS)
    except Exception as exc:
        return ConnectionTest(False, _problem(exc))
    finally:
        if source is not None:
            source.close()


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


__all__ = [
    "Attachment",
    "EmailSource",
    "ImapConfig",
    "ImapCredentials",
    "ImapSource",
    "InboundMessage",
    "InboxSnapshot",
    "MailpitSource",
    "PollOutcome",
    "build_source",
    "mailpit_address",
    "parse_email",
    "poll_due_inboxes",
    "poll_inbox",
    "process_message",
    "test_inbox_connection",
]
