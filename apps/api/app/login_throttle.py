"""Postgres-backed login attempt throttle for horizontally scaled API instances."""

import hashlib

from sqlalchemy import text
from sqlalchemy.orm import Session

MAX_ATTEMPTS_PER_WINDOW = 10
WINDOW_MINUTES = 15


def identity_hash(org_slug: str, email: str) -> str:
    return hashlib.sha256(f"{org_slug}\0{email}".encode()).hexdigest()


def reserve_attempt(session: Session, org_slug: str, email: str) -> bool:
    """Count an attempt before password work; commit so failures persist."""
    key = identity_hash(org_slug, email)
    session.execute(
        text(
            "DELETE FROM login_attempts "
            "WHERE window_started_at < now() - interval '1 day'"
        )
    )
    attempts = session.scalar(
        text(
            "INSERT INTO login_attempts (identity_hash, attempts, window_started_at) "
            "VALUES (:key, 1, now()) "
            "ON CONFLICT (identity_hash) DO UPDATE SET "
            "attempts = CASE WHEN login_attempts.window_started_at <= "
            "now() - interval '15 minutes' THEN 1 ELSE login_attempts.attempts + 1 END, "
            "window_started_at = CASE WHEN login_attempts.window_started_at <= "
            "now() - interval '15 minutes' THEN now() ELSE login_attempts.window_started_at END "
            "RETURNING attempts"
        ),
        {"key": key},
    )
    session.commit()
    return attempts is not None and attempts <= MAX_ATTEMPTS_PER_WINDOW


def clear_attempts(session: Session, org_slug: str, email: str) -> None:
    session.execute(
        text("DELETE FROM login_attempts WHERE identity_hash = :key"),
        {"key": identity_hash(org_slug, email)},
    )
    session.commit()
