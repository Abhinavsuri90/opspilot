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
