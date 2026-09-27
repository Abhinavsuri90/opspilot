"""Per-organization API keys for programmatic intake.

The plaintext key ``opk_<prefix>_<secret>`` is shown once at creation. Only its SHA-256 is
stored; the eight-character prefix is the lookup handle and the comparison is constant
time. A key authenticates only the document intake routes (see app.auth), acts as its
creator for ownership and audit, and may upload at most 60 documents per 15 minutes.
"""

import hashlib
import hmac
import json
import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import clear_api_key_context, set_api_key_context, set_org_context
from app.intake_models import ApiKey
from app.login_throttle import reserve_attempt
from app.models import AuditEvent, Membership, Organization, User
from app.repositories import (
    get_api_key,
    get_api_key_by_prefix,
    get_organization_by_id,
    get_user_by_id,
    list_api_keys,
)

KEY_PATTERN = re.compile(r"^opk_(?P<prefix>[0-9a-f]{8})_(?P<secret>[A-Za-z0-9_-]{32,64})$")
UPLOADS_PER_WINDOW = 60
THROTTLE_SCOPE = "api-key-upload"
DEFAULT_SCOPES = "documents:write"
MAX_KEYS_PER_ORG = 20


class ApiKeyRejected(Exception):
    """The presented key is malformed, unknown, revoked or its owner is no longer active."""


class ApiKeyThrottled(Exception):
    pass


class ApiKeyNotFound(Exception):
    pass


class ApiKeyLimitReached(Exception):
    pass


class ApiKeyResponse(BaseModel):
    id: uuid.UUID
    name: str
    key_prefix: str
    scopes: str
    created_by_email: str | None
    created_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None


class ApiKeyCreatedResponse(ApiKeyResponse):
    # Shown once; never stored or returned again.
    key: str


@dataclass(frozen=True)
class GeneratedKey:
    plaintext: str
    prefix: str
    key_hash: str


def hash_key(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode("ascii")).hexdigest()


def generate_key() -> GeneratedKey:
    prefix = secrets.token_hex(4)
    secret = secrets.token_urlsafe(32)
    plaintext = f"opk_{prefix}_{secret}"
    return GeneratedKey(plaintext, prefix, hash_key(plaintext))


def parse_key(token: str) -> str | None:
    """The prefix of a well-formed key, or None; the format check never touches the store."""
    match = KEY_PATTERN.match(token.strip())
    return match.group("prefix") if match else None


def describe(key: ApiKey, created_by_email: str | None) -> ApiKeyResponse:
    return ApiKeyResponse(
        id=key.id,
        name=key.name,
        key_prefix=key.key_prefix,
        scopes=key.scopes,
        created_by_email=created_by_email,
        created_at=key.created_at,
        last_used_at=key.last_used_at,
        revoked_at=key.revoked_at,
    )


def _audit(
    session: Session, org_id: uuid.UUID, user_id: uuid.UUID, event_type: str, key: ApiKey
) -> None:
    session.add(
        AuditEvent(
            org_id=org_id,
            actor_user_id=user_id,
            event_type=event_type,
            detail_json=json.dumps(
                {"api_key_id": str(key.id), "key_prefix": key.key_prefix, "name": key.name},
                sort_keys=True,
            ),
            created_at=datetime.now(UTC),
        )
    )


def create_api_key(
    session: Session, org_id: uuid.UUID, user_id: uuid.UUID, name: str
) -> ApiKeyCreatedResponse:
    active = [key for key, _ in list_api_keys(session, org_id) if key.revoked_at is None]
    if len(active) >= MAX_KEYS_PER_ORG:
        raise ApiKeyLimitReached(f"An organization may hold at most {MAX_KEYS_PER_ORG} active keys")
    creator = get_user_by_id(session, user_id)
    now = datetime.now(UTC)
    for _ in range(3):
        generated = generate_key()
        # The prefix is unique across tenants; the prefix policy lets this check see a
        # collision in another tenant without exposing anything else.
        set_api_key_context(session, generated.prefix)
        taken = get_api_key_by_prefix(session, generated.prefix) is not None
        clear_api_key_context(session)
        if taken:
            continue
        key = ApiKey(
            id=uuid.uuid4(),
            org_id=org_id,
            name=name,
            key_prefix=generated.prefix,
            key_hash=generated.key_hash,
            scopes=DEFAULT_SCOPES,
            created_by=user_id,
            created_at=now,
        )
        session.add(key)
        session.flush()
        _audit(session, org_id, user_id, "api_key.created", key)
        return ApiKeyCreatedResponse(
            **describe(key, creator.email if creator else None).model_dump(),
            key=generated.plaintext,
        )
    raise RuntimeError("Could not allocate a unique API key prefix")


def list_keys(session: Session, org_id: uuid.UUID) -> list[ApiKeyResponse]:
    return [describe(key, email) for key, email in list_api_keys(session, org_id)]


def revoke_api_key(
    session: Session, org_id: uuid.UUID, user_id: uuid.UUID, key_id: uuid.UUID
) -> ApiKeyResponse:
    key = get_api_key(session, org_id, key_id, lock=True)
    if key is None:
        raise ApiKeyNotFound("API key not found")
    if key.revoked_at is None:
        key.revoked_at = datetime.now(UTC)
        _audit(session, org_id, user_id, "api_key.revoked", key)
        session.flush()
    creator = get_user_by_id(session, key.created_by)
    return describe(key, creator.email if creator else None)


def authenticate(
    session: Session, token: str, *, charge_upload: bool
) -> tuple[ApiKey, User, Organization, Membership]:
    """Resolve a Bearer key to its tenant and acting user, or raise.

    Order matters: the upload budget is charged (and committed) before the tenant context
    is set, because the throttle commit ends the transaction that would carry SET LOCAL.
    The key row is compared in constant time; unknown prefixes take the same path.
    """
    prefix = parse_key(token)
    if prefix is None:
        raise ApiKeyRejected("Invalid API key")
    set_api_key_context(session, prefix)
    key = get_api_key_by_prefix(session, prefix)
    presented = hash_key(token.strip())
    stored = key.key_hash if key is not None else hash_key("opk_00000000_" + "0" * 32)
    if not hmac.compare_digest(stored, presented) or key is None:
        raise ApiKeyRejected("Invalid API key")
    if key.revoked_at is not None:
        raise ApiKeyRejected("API key has been revoked")
    key_id, org_id, created_by = key.id, key.org_id, key.created_by
    if charge_upload and not reserve_attempt(
        session, THROTTLE_SCOPE, str(key_id), limit=UPLOADS_PER_WINDOW
    ):
        raise ApiKeyThrottled("API key upload limit reached; try again in 15 minutes")
    set_org_context(session, org_id)
    user = get_user_by_id(session, created_by)
    org = get_organization_by_id(session, org_id)
    membership = session.scalar(
        select(Membership).where(Membership.org_id == org_id, Membership.user_id == created_by)
    )
    if user is None or org is None or membership is None or membership.status != "active":
        raise ApiKeyRejected("API key owner is no longer an active member")
    current = get_api_key(session, org_id, key_id)
    if current is None:
        raise ApiKeyRejected("Invalid API key")
    current.last_used_at = datetime.now(UTC)
    session.commit()
    # The commit ended the transaction; re-establish the tenant context for the request.
    set_org_context(session, org_id)
    return current, user, org, membership
