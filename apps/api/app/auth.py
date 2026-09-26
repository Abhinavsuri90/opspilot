"""Shared, database-checked workspace authentication for every protected route."""

import uuid
from typing import Annotated

from fastapi import Cookie, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_session, set_org_context
from app.models import Membership, Organization, User
from app.repositories import get_organization_by_id, get_user_by_id
from app.security import make_session_token, read_session_token

Identity = tuple[Session, User, Organization, Membership]


class SessionResponse(BaseModel):
    user_id: uuid.UUID
    email: str
    org_id: uuid.UUID
    org_name: str
    org_slug: str
    default_currency: str
    role: str


def describe_session(user: User, org: Organization, membership: Membership) -> SessionResponse:
    return SessionResponse(
        user_id=user.id,
        email=user.email,
        org_id=org.id,
        org_name=org.name,
        org_slug=org.slug,
        default_currency=org.default_currency,
        role=membership.role,
    )


def set_session_cookie(response: Response, user_id: uuid.UUID, org_id: uuid.UUID) -> None:
    response.set_cookie(
        key="opspilot_session",
        value=make_session_token(user_id, org_id),
        httponly=True,
        secure=get_settings().cookie_secure,
        samesite="lax",
        max_age=8 * 60 * 60,
        path="/",
    )


def membership_denial(membership: Membership) -> str:
    return {
        "pending": "Your account is awaiting approval by this organization's admin.",
        "rejected": "Your access request was declined. Contact this organization's admin.",
        "suspended": "Your organization access is suspended. Contact your admin.",
    }.get(membership.status, "Your organization membership is not active.")


def current_session(
    session: Annotated[Session, Depends(get_session)],
    opspilot_session: Annotated[str | None, Cookie()] = None,
) -> Identity:
    claims = read_session_token(opspilot_session or "")
    if claims is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    user_id, org_id = claims
    set_org_context(session, org_id)
    user = get_user_by_id(session, user_id)
    org = get_organization_by_id(session, org_id)
    # Hold this lock through the request transaction. Admin decisions take FOR
    # UPDATE on the same row, so a revocation cannot finish while an already
    # authorized mutation is still running. KEY SHARE allows concurrent reads
    # and collaboration operations without serializing every user request.
    membership = session.scalar(
        select(Membership)
        .where(Membership.org_id == org_id, Membership.user_id == user_id)
        .with_for_update(read=True, key_share=True)
    )
    if user is None or org is None or membership is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    if membership.status != "active":
        raise HTTPException(status_code=403, detail=membership_denial(membership))
    return session, user, org, membership
