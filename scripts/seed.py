"""Idempotently create fictional local demo organizations and users."""

import json
import os
import uuid

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models import Membership, Organization, User, WorkflowConfig
from app.security import hash_password, verify_password


def seed() -> None:
    password = os.environ["DEMO_PASSWORD"]
    engine = create_engine(os.environ["DATABASE_OWNER_URL"])
    demo_orgs = [
        (
            "northwind",
            "Northwind Traders",
            "northwind@example.com",
            "admin",
            "invoice",
        ),
        (
            "contoso",
            "Contoso Logistics",
            "contoso@example.com",
            "reviewer",
            "purchase_order",
        ),
    ]
    with Session(engine) as session, session.begin():
        for slug, name, email, role, document_type in demo_orgs:
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
            elif not verify_password(user.password_hash, password):
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
            else:
                membership.role = role
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
                        config_json=json.dumps(
                            {"document_types": [document_type], "fields": []}
                        ),
                    )
                )
    print("Seeded fictional demo orgs: northwind and contoso")


if __name__ == "__main__":
    seed()
