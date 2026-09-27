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
import json
import logging
import re
import socket
import ssl
import threading
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
# How often the poller thread looks for a due inbox when the previous pass found none.
POLL_TICK_SECONDS = 15
POLL_TIMEOUT_SECONDS = 30.0
MAX_MESSAGES_PER_POLL = 25
# A message is skipped without being downloaded when the server reports it larger than this.
MAX_MESSAGE_BYTES = 4 * MAX_UPLOAD_BYTES
MAX_ATTACHMENTS_PER_MESSAGE = 10
# A message whose processing keeps raising is settled (marked read, left with its error)
# after this many failed attempts so one poisonous email cannot block the inbox forever.
MAX_MESSAGE_ATTEMPTS = 3
MAX_BODY_CHARS = document_service.MAX_CONTEXT_CHARS
MAX_UID_CHARS = 400
MAILPIT_DOMAIN = "opspilot.local"
IMAP_TIMEOUT_SECONDS = 20
TOO_LARGE = "Message too large"
_RFC822_SIZE = re.compile(rb"RFC822\.SIZE\s+(\d+)")
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
    """One inbound email; ``uid`` is the idempotency key stored in email_messages.

    For IMAP the uid is ``<folder>:<uidvalidity>:<uid>`` because IMAP uids are only unique
    within one folder and one UIDVALIDITY epoch; Mailpit ids are prefixed ``mailpit:``.
    ``problem`` is set by a backend that refused the message (for example too large) so it
    is recorded and marked processed without any document being created.
    """

    uid: str
    sender: str
    subject: str
    body_text: str
    attachments: list[Attachment] = field(default_factory=list)
    problem: str | None = None

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
    considered = 0
    accepted_bytes = 0
    for part in parsed.iter_attachments():
        # Bounded work per message: at most MAX_ATTACHMENTS_PER_MESSAGE parts are looked at
        # and parsing stops once the accepted attachments reach the message size bound.
        considered += 1
        if considered > MAX_ATTACHMENTS_PER_MESSAGE or accepted_bytes >= MAX_MESSAGE_BYTES:
            break
        payload = part.get_payload(decode=True)
        if not isinstance(payload, bytes) or len(payload) > MAX_UPLOAD_BYTES:
            continue
        accepted_bytes += len(payload)
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
            for item in (body.get("Attachments") or [])[:MAX_ATTACHMENTS_PER_MESSAGE]:
                content_type = str(item.get("ContentType") or "")
                filename = str(item.get("FileName") or "attachment")
                if content_type.lower() != "application/pdf" and not filename.lower().endswith(
                    ".pdf"
                ):
                    continue
                size = item.get("Size")
                if isinstance(size, int) and size > MAX_UPLOAD_BYTES:
                    continue
                part = self.client.get(f"/api/v1/message/{message_id}/part/{item.get('PartID')}")
                part.raise_for_status()
                if len(part.content) <= MAX_UPLOAD_BYTES:
                    attachments.append(Attachment(filename, part.content, content_type))
            messages.append(
                InboundMessage(
                    f"mailpit:{message_id}",
                    sender[:320],
                    " ".join(str(body.get("Subject") or "").split())[:300],
                    _clip(str(body.get("Text") or ""), MAX_BODY_CHARS),
                    attachments,
                )
            )
        return messages

    def mark_processed(self, uid: str) -> None:
        message_id = uid.removeprefix("mailpit:")
        response = self.client.put("/api/v1/messages", json={"IDs": [message_id], "Read": True})
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
        self._uidvalidity = "0"

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
        self._uidvalidity = self._read_uidvalidity(client)
        self._client = client
        return client

    @staticmethod
    def _read_uidvalidity(client: Any) -> str:
        """The folder's UIDVALIDITY from the SELECT response; "0" when the server omits it."""
        try:
            _, data = client.response("UIDVALIDITY")
        except Exception:
            return "0"
        for item in data or []:
            text = item.decode("ascii", "ignore") if isinstance(item, bytes) else str(item or "")
            if text.strip().isdigit():
                return text.strip()
        return "0"

    def _key(self, uid: str) -> str:
        return f"{self.config.folder}:{self._uidvalidity}:{uid}"

    @staticmethod
    def _raw_uid(key: str) -> str:
        return key.rsplit(":", 1)[-1]

    @staticmethod
    def _size_of(data: list[Any]) -> int | None:
        for item in data or []:
            blob = item[0] if isinstance(item, tuple) and item else item
            if isinstance(blob, bytes):
                match = _RFC822_SIZE.search(blob)
                if match is not None:
                    return int(match.group(1))
        return None

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
            # Ask for the size first so an oversized message is never pulled into memory.
            status, data = client.uid("FETCH", uid, "(RFC822.SIZE)")
            size = self._size_of(data) if status == "OK" else None
            if size is not None and size > MAX_MESSAGE_BYTES:
                messages.append(InboundMessage(self._key(uid), "", "", "", [], TOO_LARGE))
                continue
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
            messages.append(parse_email(raw, self._key(uid)))
        return messages

    def mark_processed(self, uid: str) -> None:
        client = self._connect()
        client.uid("STORE", self._raw_uid(uid), "+FLAGS", "(\\Seen)")

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
    if isinstance(exc, StorageError):
        return str(exc)[:300] or "Object storage is unavailable"
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
    failed: int = 0
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
        existing = get_email_message(session, org_id, message.uid)
        if existing is not None and is_settled(existing):
            return None
    linked: list[uuid.UUID] = []
    created = 0
    problems: list[str] = []
    attachments = [] if message.problem else message.pdf_attachments()
    for attachment in attachments:
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
    if message.problem:
        problems.append(message.problem)
    elif not attachments:
        problems.append("No PDF attachment")
    error = "; ".join(problems)[:300] if problems else None
    with SessionLocal() as session, session.begin():
        set_org_context(session, org_id)
        row = get_email_message(session, org_id, message.uid)
        if row is None:
            row = EmailMessage(id=uuid.uuid4(), org_id=org_id, uid=message.uid[:MAX_UID_CHARS])
            session.add(row)
        row.sender = message.sender[:320]
        row.subject = message.subject[:300]
        # The first document the message points at, even when the PDF was already known;
        # document_count only counts documents this message created.
        row.document_id = linked[0] if linked else None
        row.document_count = created
        row.error = error
        # A completed pass settles the row whatever earlier attempts failed.
        row.attempts = 0
        row.processed_at = datetime.now(UTC)
    return created, error


def is_settled(row: EmailMessage) -> bool:
    """A row from a completed pass (attempts 0) or one that used up its retry budget."""
    return row.attempts == 0 or row.attempts >= MAX_MESSAGE_ATTEMPTS


def record_failure(snapshot: InboxSnapshot, message: InboundMessage, exc: BaseException) -> bool:
    """Count one failed processing attempt; True once the message must be left alone."""
    with SessionLocal() as session, session.begin():
        set_org_context(session, snapshot.org_id)
        row = get_email_message(session, snapshot.org_id, message.uid)
        if row is None:
            row = EmailMessage(
                id=uuid.uuid4(),
                org_id=snapshot.org_id,
                uid=message.uid[:MAX_UID_CHARS],
                sender=message.sender[:320],
                subject=message.subject[:300],
                document_count=0,
                attempts=0,
            )
            session.add(row)
        row.attempts += 1
        row.error = _problem(exc)
        row.processed_at = datetime.now(UTC)
        return row.attempts >= MAX_MESSAGE_ATTEMPTS


def poll_inbox(
    snapshot: InboxSnapshot,
    store: ObjectStore | None = None,
    *,
    source: EmailSource | None = None,
) -> PollOutcome:
    """Fetch new messages under a hard timeout, create documents, then mark each message.

    One message failing never aborts the batch: its attempt is counted on its row and the
    message is retried on later polls until MAX_MESSAGE_ATTEMPTS, then settled.
    """
    outcome = PollOutcome()
    object_store = store or get_store()
    opened = source
    try:
        opened = opened or build_source(snapshot)
        messages = run_connector_call(opened.fetch_new, POLL_TIMEOUT_SECONDS)
        # Processing may take a while (each PDF is parsed under its own timeout); hold the
        # lease long enough that another worker cannot claim this inbox meanwhile.
        extend_lease(
            snapshot.org_id, datetime.now(UTC) + timedelta(seconds=lease_extension_seconds())
        )
        for message in messages[:MAX_MESSAGES_PER_POLL]:
            try:
                result = process_message(snapshot, message, object_store)
            except Exception as exc:
                outcome.failed += 1
                outcome.error = _problem(exc)
                logger.warning(
                    "Message %s in inbox %s failed: %s",
                    message.uid,
                    snapshot.address,
                    outcome.error,
                )
                if not record_failure(snapshot, message, exc):
                    continue
            else:
                if result is None:
                    outcome.skipped += 1
                else:
                    outcome.messages += 1
                    outcome.documents += result[0]
            try:
                opened.mark_processed(message.uid)
            except Exception as exc:
                # The row is already settled, so a re-delivered message is skipped next time.
                outcome.error = _problem(exc)
                logger.warning(
                    "Could not mark message %s processed: %s", message.uid, outcome.error
                )
    except Exception as exc:
        outcome.error = _problem(exc)
        logger.warning("Email poll failed for inbox %s: %s", snapshot.address, outcome.error)
    finally:
        if opened is not None:
            opened.close()
    return outcome


def lease_extension_seconds() -> float:
    """Worst-case processing time for one batch: every PDF parse at its timeout plus slack."""
    return MAX_MESSAGES_PER_POLL * (get_settings().upload_parse_timeout_seconds + 5)


def extend_lease(org_id: uuid.UUID, until: datetime) -> None:
    with SessionLocal() as session, session.begin():
        set_org_context(session, org_id)
        inbox = get_email_inbox(session, org_id)
        if inbox is not None:
            inbox.next_poll_at = until


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
    """Finish a poll: the next one is due a full interval after this one completed."""
    with SessionLocal() as session, session.begin():
        set_org_context(session, org_id)
        inbox = get_email_inbox(session, org_id)
        if inbox is None:
            return
        inbox.last_polled_at = now
        inbox.last_error = outcome.error
        inbox.next_poll_at = now + timedelta(seconds=POLL_INTERVAL_SECONDS)


def poll_one_due_inbox(
    now: datetime | None = None,
    store: ObjectStore | None = None,
    *,
    org_ids: Iterable[uuid.UUID] | None = None,
) -> bool:
    """Poll the first active inbox whose next poll time has passed; False when none is due.

    ``org_ids`` limits the pass to some organizations; the poller thread leaves it unset.
    """
    now = now or datetime.now(UTC)
    if org_ids is None:
        with SessionLocal() as session:
            org_ids = list(session.scalars(select(Organization.id).order_by(Organization.id)))
    for org_id in org_ids:
        snapshot = claim_due_inbox(org_id, now)
        if snapshot is None:
            continue
        outcome = poll_inbox(snapshot, store)
        record_poll(org_id, outcome, datetime.now(UTC))
        if outcome.messages or outcome.failed or outcome.error:
            logger.info(
                "Polled inbox for org %s: %d message(s), %d document(s), %d failed, error=%s",
                org_id,
                outcome.messages,
                outcome.documents,
                outcome.failed,
                outcome.error,
            )
        return True
    return False


def poll_due_inboxes(
    now: datetime | None = None,
    store: ObjectStore | None = None,
    *,
    org_ids: Iterable[uuid.UUID] | None = None,
) -> int:
    """Poll every due inbox, one at a time. Returns the number of polls made."""
    scope = list(org_ids) if org_ids is not None else None
    polled = 0
    while poll_one_due_inbox(now, store, org_ids=scope):
        polled += 1
    return polled


def run_poller(
    stop: threading.Event,
    store: ObjectStore | None = None,
    org_ids: Iterable[uuid.UUID] | None = None,
) -> None:
    """The poller loop: one inbox per pass, a tick's rest when nothing is due, never raises.

    Runs on its own daemon thread inside the worker process (see ``start_poller``) so a slow
    or hung mailbox never delays document extraction or action execution. ``org_ids`` limits
    the loop to some organizations (tests); the worker leaves it unset.
    """
    scope = list(org_ids) if org_ids is not None else None
    while not stop.is_set():
        try:
            polled = poll_one_due_inbox(store=store, org_ids=scope)
        except Exception:
            logger.exception("Email intake pass failed; retrying after the next tick")
            polled = False
        if not polled:
            stop.wait(POLL_TICK_SECONDS)


def start_poller(
    store: ObjectStore | None = None, org_ids: Iterable[uuid.UUID] | None = None
) -> tuple[threading.Thread, threading.Event]:
    stop = threading.Event()
    thread = threading.Thread(
        target=run_poller, args=(stop, store, org_ids), name="email-intake", daemon=True
    )
    thread.start()
    return thread, stop


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
    "poll_one_due_inbox",
    "process_message",
    "run_poller",
    "start_poller",
    "test_inbox_connection",
]
