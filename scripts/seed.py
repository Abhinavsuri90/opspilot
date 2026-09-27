"""Idempotently create fictional local demo organizations and users."""

import os
import uuid

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db import normalize_database_url
from app.models import Membership, Organization, User, WorkflowConfig
from app.security import hash_password, verify_password
from app.workflow_config import default_invoice_config


def seed() -> None:
    password = os.environ["DEMO_PASSWORD"]
    reset_credentials = os.environ.get("RESET_DEMO_CREDENTIALS") == "1"
    engine = create_engine(normalize_database_url(os.environ["DATABASE_OWNER_URL"]))
    demo_orgs = [
        ("northwind", "Northwind Traders", "northwind@example.com", "admin"),
        ("contoso", "Contoso Logistics", "contoso@example.com", "reviewer"),
    ]
    with Session(engine) as session, session.begin():
        for slug, name, email, role in demo_orgs:
            org = session.scalar(select(Organization).where(Organization.slug == slug))
            if org is None:
                org = Organization(id=uuid.uuid4(), slug=slug, name=name)
                session.add(org)
            user = session.scalar(select(User).where(User.email == email))
            if user is None:
                user = User(
                    id=uuid.uuid4(), email=email, password_hash=hash_password(password)
                )
                session.add(user)
            elif reset_credentials and not verify_password(user.password_hash, password):
                user.password_hash = hash_password(password)
            session.flush()
            membership = session.scalar(
                select(Membership).where(
                    Membership.org_id == org.id, Membership.user_id == user.id
                )
            )
            if membership is None:
                session.add(
                    Membership(
                        id=uuid.uuid4(), org_id=org.id, user_id=user.id, role=role
                    )
                )
            config = session.scalar(
                select(WorkflowConfig).where(
                    WorkflowConfig.org_id == org.id, WorkflowConfig.version == 1
                )
            )
            if config is None:
                session.add(
                    WorkflowConfig(
                        id=uuid.uuid4(),
                        org_id=org.id,
                        version=1,
                        config_json=default_invoice_config().model_dump_json(),
                    )
                )
    print("Seeded fictional demo orgs: northwind and contoso")


if __name__ == "__main__":
    seed()
