import json
from pathlib import Path

import pytest
from scripts.seed import seed
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models import Base, Membership, Organization, User, WorkflowConfig
from app.security import verify_password


def test_repeat_seed_preserves_existing_password_and_role(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = f"sqlite:///{tmp_path / 'seed.db'}"
    engine = create_engine(database_url)
    Base.metadata.create_all(engine)
    monkeypatch.setenv("DATABASE_OWNER_URL", database_url)
    monkeypatch.setenv("DEMO_PASSWORD", "first-password")
    monkeypatch.delenv("RESET_DEMO_CREDENTIALS", raising=False)
    seed()

    with Session(engine) as session, session.begin():
        user = session.scalar(select(User).where(User.email == "northwind@example.com"))
        assert user is not None
        membership = session.scalar(select(Membership).where(Membership.user_id == user.id))
        assert membership is not None
        membership.role = "viewer"
        contoso = session.scalar(select(Organization).where(Organization.slug == "contoso"))
        assert contoso is not None
        config = session.scalar(
            select(WorkflowConfig).where(WorkflowConfig.org_id == contoso.id)
        )
        assert config is not None
        assert json.loads(config.config_json)["document_types"] == ["invoice"]
        config.config_json = json.dumps({"document_types": ["custom"], "fields": []})

    monkeypatch.setenv("DEMO_PASSWORD", "second-password")
    seed()
    with Session(engine) as session:
        user = session.scalar(select(User).where(User.email == "northwind@example.com"))
        assert user is not None
        membership = session.scalar(select(Membership).where(Membership.user_id == user.id))
        assert membership is not None
        assert verify_password(user.password_hash, "first-password")
        assert membership.role == "viewer"
        contoso = session.scalar(select(Organization).where(Organization.slug == "contoso"))
        assert contoso is not None
        config = session.scalar(
            select(WorkflowConfig).where(WorkflowConfig.org_id == contoso.id)
        )
        assert config is not None
        assert json.loads(config.config_json)["document_types"] == ["custom"]

    monkeypatch.setenv("RESET_DEMO_CREDENTIALS", "1")
    seed()
    with Session(engine) as session:
        user = session.scalar(select(User).where(User.email == "northwind@example.com"))
        assert user is not None
        assert verify_password(user.password_hash, "second-password")
