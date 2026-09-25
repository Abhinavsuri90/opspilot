import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from app.config import get_settings

password_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return password_hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def make_session_token(user_id: uuid.UUID, org_id: uuid.UUID) -> str:
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "org": str(org_id),
        "exp": datetime.now(UTC) + timedelta(hours=8),
    }
    return jwt.encode(payload, get_settings().jwt_secret, algorithm="HS256")


def read_session_token(token: str) -> tuple[uuid.UUID, uuid.UUID] | None:
    try:
        claims = jwt.decode(token, get_settings().jwt_secret, algorithms=["HS256"])
        return uuid.UUID(claims["sub"]), uuid.UUID(claims["org"])
    except (jwt.InvalidTokenError, KeyError, ValueError, TypeError):
        return None
