"""Postgres-backed login attempt throttle for horizontally scaled API instances."""

import hashlib

from sqlalchemy import text
from sqlalchemy.orm import Session

MAX_ATTEMPTS_PER_WINDOW = 10
# A single client address may try many accounts; this bounds credential stuffing
# without letting one shared office address lock out a whole organization.
MAX_IP_ATTEMPTS_PER_WINDOW = 50
WINDOW_MINUTES = 15


def identity_hash(org_slug: str, email: str) -> str:
    return hashlib.sha256(f"{org_slug}\0{email}".encode()).hexdigest()


def client_ip_hash(client_ip: str) -> str:
    # The "login-ip:" prefix has no NUL byte, so it can never collide with an
    # organization and email pair hashed by identity_hash.
    return hashlib.sha256(f"login-ip:{client_ip}".encode()).hexdigest()


def _reserve(session: Session, key: str, limit: int) -> bool:
    session.execute(
        text("DELETE FROM login_attempts WHERE window_started_at < now() - interval '1 day'")
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
    return attempts is not None and attempts <= limit


def reserve_attempt(
    session: Session, org_slug: str, email: str, *, limit: int = MAX_ATTEMPTS_PER_WINDOW
) -> bool:
    """Count an attempt before password work; commit so failures persist."""
    return _reserve(session, identity_hash(org_slug, email), limit)


def reserve_client_attempt(
    session: Session, client_ip: str, *, limit: int | None = None
) -> bool:
    """Count a login attempt against the client address, independent of the account."""
    return _reserve(session, client_ip_hash(client_ip), limit or MAX_IP_ATTEMPTS_PER_WINDOW)


def reserve_login(session: Session, org_slug: str, email: str, client_ip: str) -> bool:
    """Reserve both the account and the address budgets; either limit blocks the login."""
    account_ok = reserve_attempt(session, org_slug, email)
    client_ok = reserve_client_attempt(session, client_ip)
    return account_ok and client_ok


def clear_attempts(session: Session, org_slug: str, email: str) -> None:
    session.execute(
        text("DELETE FROM login_attempts WHERE identity_hash = :key"),
        {"key": identity_hash(org_slug, email)},
    )
    session.commit()
