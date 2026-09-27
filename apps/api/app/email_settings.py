"""Administrator settings for the organization's intake mailbox."""

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel
from sqlalchemy import update
from sqlalchemy.orm import Session

from app import email_intake
from app.config import get_settings
from app.connectors.base import ConnectorConfigError
from app.connectors.credentials import encrypt_credentials
from app.connectors.network import DestinationBlocked, check_host
from app.email_intake import ImapConfig, InboxSnapshot, mailpit_address, snapshot_of
from app.intake_models import EmailInbox
from app.models import AuditEvent, Organization
from app.repositories import email_message_totals, get_email_inbox


class InboxConflict(Exception):
    pass


class EmailInboxResponse(BaseModel):
    backend: str
    address: str
    config: dict[str, Any]
    has_credentials: bool
    active: bool
    version: int
    created_at: datetime
    updated_at: datetime
    last_polled_at: datetime | None
    next_poll_at: datetime | None
    last_error: str | None
    last_test_at: datetime | None
    last_test_ok: bool | None
    last_test_message: str | None
    messages_processed: int
    documents_created: int
    poll_interval_seconds: int


class InboxTestResponse(BaseModel):
    ok: bool
    message: str
    tested_at: datetime


def describe(session: Session, inbox: EmailInbox) -> EmailInboxResponse:
    try:
        config = json.loads(inbox.config_json)
    except ValueError:
        config = {}
    messages, documents = email_message_totals(session, inbox.org_id)
    return EmailInboxResponse(
        backend=inbox.backend,
        address=inbox.address,
        config=config if isinstance(config, dict) else {},
        has_credentials=inbox.credentials_encrypted is not None,
        active=inbox.active,
        version=inbox.version,
        created_at=inbox.created_at,
        updated_at=inbox.updated_at,
        last_polled_at=inbox.last_polled_at,
        next_poll_at=inbox.next_poll_at,
        last_error=inbox.last_error,
        last_test_at=inbox.last_test_at,
        last_test_ok=inbox.last_test_ok,
        last_test_message=inbox.last_test_message,
        messages_processed=messages,
        documents_created=documents,
        poll_interval_seconds=email_intake.POLL_INTERVAL_SECONDS,
    )


def read_inbox(session: Session, org_id: uuid.UUID) -> EmailInboxResponse | None:
    inbox = get_email_inbox(session, org_id)
    return describe(session, inbox) if inbox is not None else None


def _audit(
    session: Session,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    event_type: str,
    detail: dict[str, object],
) -> None:
    session.add(
        AuditEvent(
            org_id=org_id,
            actor_user_id=user_id,
            event_type=event_type,
            detail_json=json.dumps(detail, default=str, sort_keys=True),
            created_at=datetime.now(UTC),
        )
    )


def save_inbox(
    session: Session,
    org: Organization,
    user_id: uuid.UUID,
    *,
    backend: str,
    address: str | None,
    config: dict[str, Any],
    credentials: dict[str, Any] | None,
    active: bool,
    version: int,
) -> EmailInboxResponse:
    """Create (version 0) or update (matching version) the organization's inbox."""
    settings = get_settings()
    if backend == "mailpit":
        if settings.environment != "development" or not settings.mailpit_api_url:
            raise ConnectorConfigError("The Mailpit backend is only available in development")
        resolved_address = mailpit_address(org.slug)
    else:
        resolved_address = (address or "").strip().lower()
        if "@" not in resolved_address or len(resolved_address) > 320:
            raise ConnectorConfigError("address: enter the mailbox address, like ap@example.com")
    validated = email_intake.validate_inbox_config(backend, config)
    if backend == "imap":
        try:
            check_host(ImapConfig.model_validate(validated).host)
        except DestinationBlocked as exc:
            raise ConnectorConfigError(f"config.host: {exc}") from exc
    inbox = get_email_inbox(session, org.id)
    now = datetime.now(UTC)
    if inbox is None:
        if version != 0:
            raise InboxConflict("No inbox exists yet; save with version 0")
        secret = email_intake.validate_inbox_credentials(backend, credentials)
        inbox = EmailInbox(
            org_id=org.id,
            backend=backend,
            address=resolved_address,
            config_json=json.dumps(validated, sort_keys=True),
            credentials_encrypted=encrypt_credentials(secret) if secret else None,
            active=active,
            version=1,
            created_by=user_id,
            created_at=now,
            updated_at=now,
            updated_by=user_id,
        )
        session.add(inbox)
        session.flush()
        _audit(session, org.id, user_id, "email_inbox.created", {"backend": backend})
        return describe(session, inbox)
    if inbox.version != version:
        raise InboxConflict("Inbox settings changed. Refresh them before saving again.")
    if credentials is not None or backend != inbox.backend:
        secret = email_intake.validate_inbox_credentials(backend, credentials)
        inbox.credentials_encrypted = encrypt_credentials(secret) if secret else None
    elif backend == "imap" and inbox.credentials_encrypted is None:
        raise ConnectorConfigError("credentials.password: required")
    inbox.backend = backend
    inbox.address = resolved_address
    inbox.config_json = json.dumps(validated, sort_keys=True)
    inbox.active = active
    inbox.version += 1
    inbox.updated_at = now
    inbox.updated_by = user_id
    # A changed configuration is polled promptly instead of waiting out the old timer.
    inbox.next_poll_at = None
    inbox.last_error = None
    session.flush()
    _audit(
        session,
        org.id,
        user_id,
        "email_inbox.updated",
        {"backend": backend, "active": active, "credentials": credentials is not None},
    )
    return describe(session, inbox)


def test_inbox(session: Session, org: Organization, user_id: uuid.UUID) -> InboxTestResponse:
    inbox = get_email_inbox(session, org.id)
    if inbox is None:
        raise InboxConflict("Configure the inbox before testing it")
    snapshot: InboxSnapshot = snapshot_of(inbox, org.slug)
    outcome = email_intake.test_inbox_connection(snapshot)
    now = datetime.now(UTC)
    session.execute(
        update(EmailInbox)
        .where(EmailInbox.org_id == org.id)
        .values(last_test_at=now, last_test_ok=outcome.ok, last_test_message=outcome.message[:300])
    )
    _audit(
        session,
        org.id,
        user_id,
        "email_inbox.tested",
        {"ok": outcome.ok, "message": outcome.message[:300]},
    )
    session.flush()
    return InboxTestResponse(ok=outcome.ok, message=outcome.message[:300], tested_at=now)
