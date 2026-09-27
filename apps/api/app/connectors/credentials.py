"""Connector credentials at rest: Fernet under CONNECTOR_ENCRYPTION_KEY.

Outside development the key is mandatory (enforced by ``Settings``). Development derives
a local-only key from JWT_SECRET so the compose stack works without another secret; the
derived key never protects anything that leaves the developer's machine.
"""

import base64
import hashlib
import json
from functools import lru_cache
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings
from app.connectors.base import CredentialsUnavailable

_DEV_KEY_CONTEXT = b"opspilot-connector-credentials:"


def derive_development_key(jwt_secret: str) -> str:
    digest = hashlib.sha256(_DEV_KEY_CONTEXT + jwt_secret.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii")


@lru_cache
def _fernet() -> Fernet:
    settings = get_settings()
    key = settings.connector_encryption_key
    if key is None:
        if settings.environment != "development":
            raise CredentialsUnavailable("CONNECTOR_ENCRYPTION_KEY is not configured")
        key = derive_development_key(settings.jwt_secret)
    return Fernet(key.encode("ascii"))


def encrypt_credentials(credentials: dict[str, Any]) -> str:
    payload = json.dumps(credentials, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return _fernet().encrypt(payload).decode("ascii")


def decrypt_credentials(token: str) -> dict[str, Any]:
    try:
        payload = _fernet().decrypt(token.encode("ascii"))
        decoded = json.loads(payload.decode("utf-8"))
    except (InvalidToken, ValueError) as exc:
        raise CredentialsUnavailable(
            "Stored credentials cannot be decrypted with the configured key"
        ) from exc
    if not isinstance(decoded, dict):
        raise CredentialsUnavailable("Stored credentials are malformed")
    return {str(key): value for key, value in decoded.items()}
