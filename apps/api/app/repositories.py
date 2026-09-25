import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Membership, Organization, User


def get_organization_by_slug(session: Session, slug: str) -> Organization | None:
    return session.scalar(select(Organization).where(Organization.slug == slug))


def get_user_by_email(session: Session, email: str) -> User | None:
    return session.scalar(select(User).where(User.email == email))


def get_user_by_id(session: Session, user_id: uuid.UUID) -> User | None:
    return session.scalar(select(User).where(User.id == user_id))


def get_organization_by_id(session: Session, org_id: uuid.UUID) -> Organization | None:
    return session.scalar(select(Organization).where(Organization.id == org_id))


def get_membership(session: Session, org_id: uuid.UUID, user_id: uuid.UUID) -> Membership | None:
    return session.scalar(
        select(Membership).where(Membership.org_id == org_id, Membership.user_id == user_id)
    )


def list_members(session: Session, org_id: uuid.UUID) -> list[tuple[Membership, User]]:
    rows = session.execute(
        select(Membership, User)
        .join(User, User.id == Membership.user_id)
        .where(Membership.org_id == org_id)
        .order_by(User.email)
    )
    return [(membership, user) for membership, user in rows]
