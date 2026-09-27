"""Idempotently create fictional local demo organizations and users.

Northwind Traders starts from the invoice template with a CSV export destination; Contoso
Logistics starts from the logistics template (purchase orders and delivery notes). An
organization whose workflow configuration was edited keeps its edits; only the untouched
default invoice configuration is upgraded to the demo shape.
"""

import json
import os
import uuid
from datetime import UTC, datetime

from pydantic import ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.action_models import ConnectorInstance, OrgSettings
from app.db import normalize_database_url
from app.models import Membership, Organization, User, WorkflowConfig
from app.security import hash_password, verify_password
from app.workflow_config import (
    DestinationSpec,
    WorkflowConfigModel,
    default_invoice_config,
    template_config,
)

DEMO_ORGS = [
    ("northwind", "Northwind Traders", "northwind@example.com", "admin", "invoice"),
    ("northwind", "Northwind Traders", "northwind.reviewer@example.com", "reviewer", "invoice"),
    ("northwind", "Northwind Traders", "northwind.member@example.com", "member", "invoice"),
    ("contoso", "Contoso Logistics", "contoso.admin@example.com", "admin", "logistics"),
    ("contoso", "Contoso Logistics", "contoso@example.com", "reviewer", "logistics"),
    ("contoso", "Contoso Logistics", "contoso.member@example.com", "member", "logistics"),
]
EXPORT_CONNECTOR = "archive"
# Demo organizations get a strict daily model budget so a public demo cannot run up a bill.
DEMO_DAILY_LLM_SPEND_CAP_CENTS = 100


def earlier_demo_shapes(slug: str, template: str) -> list[dict[str, object]]:
    """Configurations an earlier seed wrote for this organization, as stored JSON.

    The logistics template first shipped with purchase orders and delivery notes only; the
    supplier invoice type was added later. A row that still matches that shape was never
    edited and is upgraded like the default.
    """
    wanted = demo_config(slug, template)
    shapes: list[dict[str, object]] = []
    if template == "logistics":
        without_invoice = WorkflowConfigModel.model_validate(
            {
                **wanted.model_dump(),
                "document_types": [
                    item.model_dump() for item in wanted.document_types if item.name != "invoice"
                ],
            }
        )
        shapes.append(json.loads(without_invoice.model_dump_json()))
    return shapes


def is_untouched_default(raw: object, slug: str = "", template: str = "invoice") -> bool:
    """True when nobody edited the configuration through the settings editor.

    Rows written before the editor existed hold the Phase 1 shape (a list of type names)
    and load as the default invoice workflow; the editor only ever writes full models. A
    full model that still equals the invoice template, or a shape an earlier seed wrote for
    this organization, is untouched as well.
    """
    if not isinstance(raw, dict):
        return False
    types = raw.get("document_types")
    legacy = not isinstance(types, list) or not types or all(isinstance(t, str) for t in types)
    if legacy:
        return True
    if raw in earlier_demo_shapes(slug, template):
        return True
    try:
        return WorkflowConfigModel.model_validate(raw) == default_invoice_config()
    except ValidationError:
        return False


def demo_config(slug: str, template: str) -> WorkflowConfigModel:
    config = template_config(template)
    if slug != "northwind":
        return config
    destination = DestinationSpec(
        name="monthly-csv",
        connector=EXPORT_CONNECTOR,
        action_type="export_csv",
        mapping={
            "vendor": "vendor",
            "invoice_number": "invoice_number",
            "invoice_date": "invoice_date",
            "total": "total",
            "currency": "currency",
            "document": "${document.filename}",
        },
    )
    return WorkflowConfigModel.model_validate(
        {**config.model_dump(), "destinations": [destination.model_dump()]}
    )


def ensure_export_connector(session: Session, org_id: uuid.UUID) -> None:
    existing = session.scalar(
        select(ConnectorInstance).where(
            ConnectorInstance.org_id == org_id, ConnectorInstance.name == EXPORT_CONNECTOR
        )
    )
    if existing is None:
        now = datetime.now(UTC)
        session.add(
            ConnectorInstance(
                id=uuid.uuid4(),
                org_id=org_id,
                name=EXPORT_CONNECTOR,
                connector_type="csv_export",
                config_json=json.dumps({"file_prefix": "northwind"}),
                active=True,
                version=1,
                created_at=now,
                updated_at=now,
            )
        )


def ensure_spend_cap(session: Session, org_id: uuid.UUID) -> None:
    """Set the demo budget once; an administrator's explicit value is left alone."""
    settings = session.scalar(select(OrgSettings).where(OrgSettings.org_id == org_id))
    if settings is None:
        session.add(
            OrgSettings(
                org_id=org_id,
                daily_llm_spend_cap_cents=DEMO_DAILY_LLM_SPEND_CAP_CENTS,
                updated_at=datetime.now(UTC),
            )
        )
    elif settings.daily_llm_spend_cap_cents is None and settings.version == 0:
        settings.daily_llm_spend_cap_cents = DEMO_DAILY_LLM_SPEND_CAP_CENTS


def ensure_workflow(session: Session, org_id: uuid.UUID, slug: str, template: str) -> None:
    latest = session.scalar(
        select(WorkflowConfig)
        .where(WorkflowConfig.org_id == org_id)
        .order_by(WorkflowConfig.version.desc())
        .limit(1)
    )
    wanted = demo_config(slug, template)
    if latest is None:
        version = 1
    else:
        try:
            current = json.loads(latest.config_json)
        except ValueError:
            return
        if current == json.loads(wanted.model_dump_json()) or not is_untouched_default(
            current, slug, template
        ):
            # Already the demo shape, or edited by hand: leave it alone.
            return
        version = latest.version + 1
    session.add(
        WorkflowConfig(
            id=uuid.uuid4(), org_id=org_id, version=version, config_json=wanted.model_dump_json()
        )
    )


def seed() -> None:
    if os.environ.get("ENVIRONMENT", "development") != "development":
        raise RuntimeError("Fictional demo accounts may only be seeded in development")
    password = os.environ["DEMO_PASSWORD"]
    reset_credentials = os.environ.get("RESET_DEMO_CREDENTIALS") == "1"
    engine = create_engine(normalize_database_url(os.environ["DATABASE_OWNER_URL"]))
    with Session(engine) as session, session.begin():
        for slug, name, email, role, template in DEMO_ORGS:
            org = session.scalar(select(Organization).where(Organization.slug == slug))
            if org is None:
                org = Organization(id=uuid.uuid4(), slug=slug, name=name)
                session.add(org)
            elif org.name != name:
                raise RuntimeError(f"Existing organization {slug!r} is not the fictional demo org")
            user = session.scalar(select(User).where(User.email == email))
            if user is None:
                user = User(id=uuid.uuid4(), email=email, password_hash=hash_password(password))
                session.add(user)
            elif reset_credentials and not verify_password(user.password_hash, password):
                user.password_hash = hash_password(password)
            session.flush()
            membership = session.scalar(
                select(Membership).where(Membership.org_id == org.id, Membership.user_id == user.id)
            )
            if membership is None:
                session.add(Membership(id=uuid.uuid4(), org_id=org.id, user_id=user.id, role=role))
            if slug == "northwind":
                ensure_export_connector(session, org.id)
            ensure_spend_cap(session, org.id)
            session.flush()
            ensure_workflow(session, org.id, slug, template)
    print("Seeded fictional demo orgs and admin/reviewer/member accounts: northwind, contoso")


if __name__ == "__main__":
    seed()
