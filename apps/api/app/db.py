import uuid
from collections.abc import Iterator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings


def normalize_database_url(url: str) -> str:
    """Use the installed psycopg 3 driver for common hosted Postgres URLs."""
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix) :]
    return url


engine = create_engine(normalize_database_url(get_settings().database_url), pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def get_session() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session


def set_org_context(session: Session, org_id: uuid.UUID) -> None:
    # SET LOCAL expires at transaction end, so pooled connections cannot retain another tenant.
    session.execute(
        text("SELECT set_config('app.current_org', :org_id, true)"), {"org_id": str(org_id)}
    )


def set_api_key_context(session: Session, key_prefix: str) -> None:
    """Expose exactly one api_keys row (by public prefix) before the tenant is known.

    The api_keys table has a second, SELECT-only policy keyed on this setting, so a lookup
    can run without a tenant context and still never see another key. SET LOCAL scope again.
    """
    if session.get_bind().dialect.name != "postgresql":
        return
    session.execute(
        text("SELECT set_config('app.api_key_prefix', :prefix, true)"), {"prefix": key_prefix}
    )


def clear_api_key_context(session: Session) -> None:
    """Withdraw the prefix policy once the lookup is done (the policy treats '' as unset)."""
    set_api_key_context(session, "")
