"""Shared test setup: development environment, throttle hygiene and Postgres cleanup."""

import os
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field

# Settings fail closed to production checks unless told otherwise; tests never
# carry deployment secrets, so pin the development profile before app import.
os.environ.setdefault("ENVIRONMENT", "development")

import pytest  # noqa: E402
from sqlalchemy import Engine, create_engine, delete, select, text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.action_models import (  # noqa: E402
    Action,
    ActionAttempt,
    ConnectorInstance,
    OrgActionPolicy,
    OrgSettings,
)
from app.db import normalize_database_url  # noqa: E402
from app.login_throttle import client_ip_hash, identity_hash  # noqa: E402
from app.models import (  # noqa: E402
    AuditEvent,
    Document,
    ExtractedField,
    ExtractionRun,
    LoginAttempt,
    Membership,
    Organization,
    OutboxEvent,
    User,
    WorkflowConfig,
)
from app.security import make_session_token  # noqa: E402
from app.workflow_config import WorkflowConfigModel, default_invoice_config  # noqa: E402
from app.workflow_models import (  # noqa: E402
    FieldCorrection,
    InvoiceCategory,
    InvoiceComment,
    InvoiceGrant,
    InvoiceMetadata,
    InvoiceReview,
    ReviewTask,
)

POSTGRES_AVAILABLE = "DATABASE_OWNER_URL" in os.environ
postgres = pytest.mark.skipif(not POSTGRES_AVAILABLE, reason="Postgres integration test")
# Starlette's TestClient reports this peer address for every request.
TEST_CLIENT_HOST = "testclient"


def owner_engine() -> Engine:
    return create_engine(normalize_database_url(os.environ["DATABASE_OWNER_URL"]))


def delete_documents(session: Session, document_ids: list[uuid.UUID]) -> None:
    """Remove documents and every dependent row, children first, with owner rights."""
    if not document_ids:
        return
    action_ids = list(
        session.scalars(select(Action.id).where(Action.document_id.in_(document_ids)))
    )
    if action_ids:
        session.execute(delete(ActionAttempt).where(ActionAttempt.action_id.in_(action_ids)))
    for model in (
        Action,
        FieldCorrection,
        ReviewTask,
        InvoiceReview,
        InvoiceGrant,
        InvoiceComment,
        InvoiceMetadata,
        ExtractedField,
        ExtractionRun,
        OutboxEvent,
    ):
        session.execute(delete(model).where(model.document_id.in_(document_ids)))
    session.execute(delete(AuditEvent).where(AuditEvent.document_id.in_(document_ids)))
    session.execute(delete(Document).where(Document.id.in_(document_ids)))


def delete_organizations(session: Session, org_ids: list[uuid.UUID]) -> None:
    """Remove test organizations, their documents, memberships and orphaned users."""
    if not org_ids:
        return
    documents = list(
        session.scalars(select(Document.id).where(Document.org_id.in_(org_ids)))
    )
    delete_documents(session, documents)
    user_ids = list(
        session.scalars(select(Membership.user_id).where(Membership.org_id.in_(org_ids)))
    )
    for model in (
        ConnectorInstance,
        OrgActionPolicy,
        OrgSettings,
        InvoiceCategory,
        AuditEvent,
        WorkflowConfig,
        Membership,
    ):
        session.execute(delete(model).where(model.org_id.in_(org_ids)))
    session.execute(delete(Organization).where(Organization.id.in_(org_ids)))
    if user_ids:
        session.execute(
            delete(User).where(User.id.in_(user_ids), ~User.id.in_(select(Membership.user_id)))
        )


@pytest.fixture(autouse=True)
def reset_test_client_throttle() -> Iterator[None]:
    """Every test shares one peer address; keep per-address limits from crossing tests."""
    yield
    if not POSTGRES_AVAILABLE:
        return
    engine = owner_engine()
    try:
        with Session(engine) as session, session.begin():
            session.execute(
                delete(LoginAttempt).where(
                    LoginAttempt.identity_hash.in_(
                        [
                            client_ip_hash(TEST_CLIENT_HOST),
                            identity_hash("signup-peer", TEST_CLIENT_HOST),
                        ]
                    )
                )
            )
    finally:
        engine.dispose()


@pytest.fixture
def demo_document_cleanup() -> Iterator[None]:
    """Delete any document a test adds to the shared demo organizations."""
    if not POSTGRES_AVAILABLE:
        yield
        return
    engine = owner_engine()
    with Session(engine) as session:
        before = set(session.scalars(select(Document.id)))
    try:
        yield
    finally:
        with Session(engine) as session, session.begin():
            after = set(session.scalars(select(Document.id)))
            delete_documents(session, sorted(after - before))
        engine.dispose()


@dataclass
class Tenant:
    """An isolated organization with one user per role, removed after the test."""

    org_id: uuid.UUID
    slug: str
    users: dict[str, uuid.UUID]
    config_version: int = 1
    extra_org_ids: list[uuid.UUID] = field(default_factory=list)

    def token(self, role: str) -> str:
        return make_session_token(self.users[role], self.org_id)

    def email(self, role: str) -> str:
        return f"{role}-{self.users[role].hex}@example.com"


TenantFactory = Callable[..., Tenant]


@pytest.fixture
def make_tenant() -> Iterator[TenantFactory]:
    engine = owner_engine() if POSTGRES_AVAILABLE else None
    created: list[Tenant] = []

    def factory(
        config: WorkflowConfigModel | None = None,
        roles: tuple[str, ...] = ("admin", "reviewer", "member", "viewer"),
        default_currency: str = "USD",
    ) -> Tenant:
        if engine is None:
            pytest.skip("Postgres integration test")
        org_id = uuid.uuid4()
        users = {role: uuid.uuid4() for role in roles}
        tenant = Tenant(org_id, f"tenant-{org_id.hex[:12]}", users)
        with Session(engine) as session, session.begin():
            session.add(
                Organization(
                    id=org_id,
                    slug=tenant.slug,
                    name=f"Tenant {org_id.hex[:6]}",
                    default_currency=default_currency,
                )
            )
            for role, user_id in users.items():
                session.add(
                    User(id=user_id, email=tenant.email(role), password_hash="unused-token-test")
                )
            session.flush()
            for role, user_id in users.items():
                session.add(
                    Membership(org_id=org_id, user_id=user_id, role=role, status="active")
                )
            session.add(
                WorkflowConfig(
                    org_id=org_id,
                    version=1,
                    config_json=(config or default_invoice_config()).model_dump_json(),
                )
            )
        created.append(tenant)
        return tenant

    yield factory
    if engine is not None:
        with Session(engine) as session, session.begin():
            org_ids = [tenant.org_id for tenant in created]
            org_ids += [extra for tenant in created for extra in tenant.extra_org_ids]
            delete_organizations(session, org_ids)
            session.execute(text("SELECT 1"))
        engine.dispose()
