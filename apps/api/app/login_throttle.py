"""Postgres-backed login attempt throttle for horizontally scaled API instances."""

import hashlib

from sqlalchemy import text
from sqlalchemy.orm import Session

MAX_ATTEMPTS_PER_WINDOW = 10
# A single client address may try many accounts; this bounds credential stuffing.
# Only failures count, so a shared office address is not locked out by successes.
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


def client_blocked(session: Session, client_ip: str, *, limit: int | None = None) -> bool:
    """Whether the address already spent its failure budget in the current window.

    Only failed credential checks are charged (see record_client_failure), so many
    people signing in correctly from one shared address never block each other.
    """
    attempts = session.scalar(
        text(
            "SELECT attempts FROM login_attempts WHERE identity_hash = :key "
            "AND window_started_at > now() - interval '15 minutes'"
        ),
        {"key": client_ip_hash(client_ip)},
    )
    return attempts is not None and attempts >= (limit or MAX_IP_ATTEMPTS_PER_WINDOW)


def record_client_failure(session: Session, client_ip: str) -> None:
    """Charge one failed login to the client address; commits so the count persists."""
    _reserve(session, client_ip_hash(client_ip), MAX_IP_ATTEMPTS_PER_WINDOW)


def clear_attempts(session: Session, org_slug: str, email: str) -> None:
    session.execute(
        text("DELETE FROM login_attempts WHERE identity_hash = :key"),
        {"key": identity_hash(org_slug, email)},
    )
    session.commit()
