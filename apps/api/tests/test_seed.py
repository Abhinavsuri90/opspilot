import json
from pathlib import Path

import pytest
from scripts.seed import seed
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.action_models import ConnectorInstance
from app.models import Base, Membership, Organization, User, WorkflowConfig
from app.security import verify_password
from app.workflow_config import default_invoice_config


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
        stored = json.loads(config.config_json)
        assert [item["name"] for item in stored["document_types"]] == [
            "purchase_order",
            "delivery_note",
        ]
        assert stored["review_policy"] == "always" and stored["destinations"] == []
        # An administrator's edit (a full model the settings editor would write) is kept.
        edited = default_invoice_config().model_copy(update={"baseline_minutes": 20})
        config.config_json = edited.model_dump_json()
        northwind = session.scalar(select(Organization).where(Organization.slug == "northwind"))
        assert northwind is not None
        northwind_config = session.scalar(
            select(WorkflowConfig).where(WorkflowConfig.org_id == northwind.id)
        )
        assert northwind_config is not None
        northwind_stored = json.loads(northwind_config.config_json)
        assert northwind_stored["document_types"][0]["name"] == "invoice"
        assert [item["name"] for item in northwind_stored["destinations"]] == ["monthly-csv"]
        assert northwind_stored["destinations"][0]["connector"] == "archive"
        connector = session.scalar(
            select(ConnectorInstance).where(ConnectorInstance.org_id == northwind.id)
        )
        assert connector is not None and connector.connector_type == "csv_export"

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
        assert json.loads(config.config_json)["baseline_minutes"] == 20
        assert json.loads(config.config_json)["document_types"][0]["name"] == "invoice"
        assert (
            session.scalar(
                select(func.count(WorkflowConfig.id)).where(WorkflowConfig.org_id == contoso.id)
            )
            == 1
        )

    monkeypatch.setenv("RESET_DEMO_CREDENTIALS", "1")
    seed()
    with Session(engine) as session:
        user = session.scalar(select(User).where(User.email == "northwind@example.com"))
        assert user is not None
        assert verify_password(user.password_hash, "second-password")


def test_seed_upgrades_an_untouched_default_configuration_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = f"sqlite:///{tmp_path / 'upgrade.db'}"
    engine = create_engine(database_url)
    Base.metadata.create_all(engine)
    monkeypatch.setenv("DATABASE_OWNER_URL", database_url)
    monkeypatch.setenv("DEMO_PASSWORD", "first-password")
    with Session(engine) as session, session.begin():
        # Northwind still has the current default; Contoso has a Phase 1 legacy row, which
        # loads as the invoice default whatever names it lists.
        for slug, name, stored in (
            ("northwind", "Northwind Traders", default_invoice_config().model_dump_json()),
            ("contoso", "Contoso Logistics", '{"document_types": ["custom"], "fields": []}'),
        ):
            org = Organization(slug=slug, name=name)
            session.add(org)
            session.flush()
            session.add(WorkflowConfig(org_id=org.id, version=1, config_json=stored))
    seed()
    with Session(engine) as session:
        for slug, first_type in (("northwind", "invoice"), ("contoso", "purchase_order")):
            seeded = session.scalar(select(Organization).where(Organization.slug == slug))
            assert seeded is not None
            versions = session.scalars(
                select(WorkflowConfig)
                .where(WorkflowConfig.org_id == seeded.id)
                .order_by(WorkflowConfig.version)
            ).all()
            assert [row.version for row in versions] == [1, 2]
            latest = json.loads(versions[-1].config_json)
            assert latest["document_types"][0]["name"] == first_type
    seed()
    with Session(engine) as session:
        assert session.scalar(select(func.count(WorkflowConfig.id))) == 4
