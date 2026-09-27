"""Public workspace signup and tenant-scoped administrator membership decisions."""

import json
import uuid
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import (
    Identity,
    SessionResponse,
    current_session,
    describe_session,
    set_session_cookie,
)
from app.client_ip import client_ip
from app.db import get_session, set_org_context
from app.login_throttle import reserve_attempt
from app.models import AuditEvent, Membership, Organization, User, WorkflowConfig
from app.repositories import (
    get_membership,
    get_organization_by_slug,
    get_user_by_email,
    list_members,
)
from app.security import hash_password, verify_password
from app.workflow_config import Template, template_config

router = APIRouter(tags=["Organizations"])
SLUG_PATTERN = r"^[a-z0-9](?:[a-z0-9-]{0,78}[a-z0-9])?$"


class SignupCredentials(BaseModel):
    email: EmailStr
    password: str = Field(min_length=12, max_length=128)
    org_slug: str = Field(min_length=1, max_length=80, pattern=SLUG_PATTERN)

    @field_validator("email", "org_slug", mode="before")
    @classmethod
    def normalize_identifier(cls, value: object) -> object:
        return value.strip().lower() if isinstance(value, str) else value

    @field_validator("password")
    @classmethod
    def password_strength(cls, value: str) -> str:
        if not any(char.isalpha() for char in value) or not any(char.isdigit() for char in value):
            raise ValueError("Use at least 12 characters including a letter and a number")
        return value


class RegisterOrganizationRequest(SignupCredentials):
    org_name: str = Field(min_length=2, max_length=200)
    default_currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")
    # Starting workflow: invoices, or purchase orders and delivery notes (logistics).
    template: Template = "invoice"

    @field_validator("org_name", mode="before")
    @classmethod
    def normalize_name(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("default_currency", mode="before")
    @classmethod
    def normalize_currency(cls, value: object) -> object:
        return value.strip().upper() if isinstance(value, str) else value


class JoinOrganizationRequest(SignupCredentials):
    requested_role: Literal["member", "reviewer"] = "member"


class OrganizationResponse(BaseModel):
    id: uuid.UUID
    slug: str
    name: str


class JoinOrganizationResponse(BaseModel):
    org_id: uuid.UUID
    org_name: str
    status: Literal["pending"] = "pending"
    message: str = "Your request was submitted. An organization admin must approve your access."


class MemberResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    email: str
    role: str
    status: str
    requested_role: str
    created_at: datetime
    decided_at: datetime | None


class MembershipDecisionRequest(BaseModel):
    decision: Literal["approved", "rejected", "suspended"]
    role: Literal["member", "reviewer", "viewer"] | None = None


def describe_member(membership: Membership, user: User) -> MemberResponse:
    return MemberResponse(
        id=membership.id,
        user_id=user.id,
        email=user.email,
        role=membership.role,
        status=membership.status,
        requested_role=membership.requested_role or membership.role,
        created_at=membership.created_at,
        decided_at=membership.decided_at,
    )


def reserve_signup(request: Request, session: Session, email: str) -> None:
    # The address limit is a backstop behind the web proxy; deployments should
    # also rate-limit at the edge. client_ip only trusts edge-appended forwarding.
    peer = client_ip(request)
    if not reserve_attempt(session, "signup-peer", peer, limit=100) or not reserve_attempt(
        session, "signup-email", email
    ):
        raise HTTPException(
            status_code=429, detail="Too many signup attempts; try again in 15 minutes"
        )


def signup_user(session: Session, email: str, password: str) -> User:
    # An email is a global identity. Joining or creating another workspace must
    # prove ownership of an existing account and must never reset its password.
    user = get_user_by_email(session, email)
    if user is not None:
        if not verify_password(user.password_hash, password):
            raise HTTPException(
                status_code=401, detail="Invalid credentials for this email address"
            )
        return user
    user = User(id=uuid.uuid4(), email=email, password_hash=hash_password(password))
    session.add(user)
    session.flush()
    return user


@router.get("/v1/organizations", response_model=list[OrganizationResponse])
def organizations(
    session: Annotated[Session, Depends(get_session)],
    search: Annotated[str, Query(max_length=100)] = "",
) -> list[OrganizationResponse]:
    query = select(Organization).order_by(Organization.name, Organization.slug).limit(50)
    term = search.strip()
    if term:
        query = query.where(
            Organization.name.icontains(term, autoescape=True)
            | Organization.slug.icontains(term, autoescape=True)
        )
    return [
        OrganizationResponse(id=org.id, slug=org.slug, name=org.name)
        for org in session.scalars(query)
    ]


@router.post("/v1/auth/register-organization", response_model=SessionResponse, status_code=201)
def register_organization(
    body: RegisterOrganizationRequest,
    request: Request,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
) -> SessionResponse:
    reserve_signup(request, session, str(body.email))
    if get_organization_by_slug(session, body.org_slug) is not None:
        raise HTTPException(
            status_code=409, detail="This organization address is already registered"
        )
    try:
        user = signup_user(session, str(body.email), body.password)
        org = Organization(
            id=uuid.uuid4(),
            name=body.org_name,
            slug=body.org_slug,
            default_currency=body.default_currency,
        )
        session.add(org)
        session.flush()
        set_org_context(session, org.id)
        membership = Membership(
            org_id=org.id,
            user_id=user.id,
            role="admin",
            status="active",
            requested_role="admin",
            decided_at=datetime.now(UTC),
            decided_by=user.id,
        )
        session.add_all(
            [
                membership,
                WorkflowConfig(
                    org_id=org.id,
                    version=1,
                    config_json=template_config(body.template).model_dump_json(),
                ),
                AuditEvent(
                    org_id=org.id,
                    actor_user_id=user.id,
                    event_type="organization.created",
                    detail_json=json.dumps(
                        {
                            "slug": org.slug,
                            "default_currency": org.default_currency,
                            "template": body.template,
                        }
                    ),
                ),
            ]
        )
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail="Organization or account was just created. Try signing in or retrying.",
        ) from exc
    set_session_cookie(response, user.id, org.id)
    return describe_session(user, org, membership)


@router.post("/v1/auth/join-organization", response_model=JoinOrganizationResponse, status_code=201)
def join_organization(
    body: JoinOrganizationRequest,
    request: Request,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
) -> JoinOrganizationResponse:
    reserve_signup(request, session, str(body.email))
    org = get_organization_by_slug(session, body.org_slug)
    if org is None:
        raise HTTPException(
            status_code=404, detail="Organization not found. Check its workspace address."
        )
    try:
        user = signup_user(session, str(body.email), body.password)
        set_org_context(session, org.id)
        existing = get_membership(session, org.id, user.id)
        if existing is not None:
            raise HTTPException(
                status_code=409,
                detail={
                    "active": "You already belong to this organization. Sign in instead.",
                    "pending": "Your access request is already awaiting admin approval.",
                }.get(existing.status, "Contact the organization admin to restore your access."),
            )
        session.add_all(
            [
                Membership(
                    org_id=org.id,
                    user_id=user.id,
                    role=body.requested_role,
                    requested_role=body.requested_role,
                    status="pending",
                ),
                AuditEvent(
                    org_id=org.id,
                    actor_user_id=user.id,
                    event_type="membership.requested",
                    detail_json=json.dumps({"requested_role": body.requested_role}),
                ),
            ]
        )
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(
            status_code=409, detail="An account or membership already exists. Try again."
        ) from exc
    # A join request is never an authenticated session, even if the browser
    # previously had a cookie for another organization.
    response.delete_cookie("opspilot_session", path="/")
    return JoinOrganizationResponse(org_id=org.id, org_name=org.name)


@router.get("/v1/organization/members", response_model=list[MemberResponse])
def organization_members(
    identity: Annotated[Identity, Depends(current_session)],
) -> list[MemberResponse]:
    session, _, org, membership = identity
    if membership.role != "admin":
        raise HTTPException(status_code=403, detail="Admin role required")
    return [describe_member(member, user) for member, user in list_members(session, org.id)]


@router.post("/v1/organization/members/{user_id}/decision", response_model=MemberResponse)
def decide_membership(
    user_id: uuid.UUID,
    body: MembershipDecisionRequest,
    identity: Annotated[Identity, Depends(current_session)],
) -> MemberResponse:
    session, actor, org, acting_membership = identity
    if acting_membership.role != "admin":
        raise HTTPException(status_code=403, detail="Admin role required")
    # Serialize decisions in a workspace and lock the target row. In particular,
    # suspension cannot race approval into granting access from a stale snapshot.
    session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:org_id, 0))"), {"org_id": str(org.id)}
    )
    admin_denial = HTTPException(
        status_code=409, detail="Admin access cannot be changed through member approval"
    )
    # Read before locking: two admins deciding on each other each hold a KEY SHARE
    # lock on their own row, so a FOR UPDATE on an admin row could form a lock cycle.
    unlocked = session.scalar(
        select(Membership).where(Membership.org_id == org.id, Membership.user_id == user_id)
    )
    if unlocked is None:
        raise HTTPException(status_code=404, detail="Organization member not found")
    if unlocked.role == "admin":
        raise admin_denial
    member = session.scalar(
        select(Membership)
        .where(
            Membership.org_id == org.id,
            Membership.user_id == user_id,
            Membership.role != "admin",
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if member is None:
        # The row became an admin between the two reads.
        raise admin_denial
    if body.decision == "rejected" and member.status not in {"pending", "rejected"}:
        raise HTTPException(
            status_code=409, detail="Suspend an active account to revoke its access"
        )
    if body.decision == "suspended" and member.status not in {"active", "suspended"}:
        raise HTTPException(status_code=409, detail="Only an active account can be suspended")
    previous_status, previous_role = member.status, member.role
    member.status = {"approved": "active", "rejected": "rejected", "suspended": "suspended"}[
        body.decision
    ]
    if body.decision == "approved":
        member.role = body.role or member.requested_role or member.role
    member.decided_at = datetime.now(UTC)
    member.decided_by = actor.id
    session.add(
        AuditEvent(
            org_id=org.id,
            actor_user_id=actor.id,
            event_type=f"membership.{body.decision}",
            detail_json=json.dumps(
                {
                    "user_id": str(user_id),
                    "previous_status": previous_status,
                    "status": member.status,
                    "previous_role": previous_role,
                    "role": member.role,
                }
            ),
        )
    )
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Organization member not found")
    result = describe_member(member, user)
    session.commit()
    return result
