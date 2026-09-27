"""Tenant scoped invoice review, sharing, categories and grounded workspace answers."""

import json
import re
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import and_, case, delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import actions_service, review_service
from app.access import accessible_document_clause, can_access_document
from app.auth import Identity, current_session
from app.models import AuditEvent, Document, ExtractedField, Membership, Organization, User
from app.review_service import DocumentDetail, QueueItem, TimelineEntry
from app.workflow_models import (
    InvoiceCategory,
    InvoiceComment,
    InvoiceGrant,
    InvoiceMetadata,
    InvoiceReview,
)

__all__ = ["accessible_document_clause", "can_access_document", "router"]

router = APIRouter(prefix="/v1", tags=["Invoice workspace"])
SessionContext = Annotated[Identity, Depends(current_session)]
# Explicit supported ISO 4217 codes; a dollar sign is never treated as a currency.
SUPPORTED_CURRENCIES = frozenset(
    "AED AUD BDT BGN BHD BRL CAD CHF CLP CNY COP CZK DKK EGP EUR GBP HKD HUF IDR ILS "
    "INR ISK JPY KES KRW KWD LKR MAD MXN MYR NGN NOK NPR NZD OMR PEN PHP PKR PLN QAR "
    "RON RSD RUB SAR SEK SGD THB TRY TWD UAH USD UYU VND ZAR".split()
)


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class CategoryCreate(RequestModel):
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=500)


class CategoryUpdate(RequestModel):
    version: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=500)
    active: bool | None = None

    @model_validator(mode="after")
    def reject_null_changes(self) -> "CategoryUpdate":
        for key in self.model_fields_set - {"version"}:
            if getattr(self, key) is None:
                raise ValueError(f"{key} cannot be null")
        return self


class CategoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    description: str
    active: bool
    version: int


class MetadataUpdate(RequestModel):
    version: int = Field(ge=0)
    category_id: uuid.UUID | None = None
    assigned_reviewer_id: uuid.UUID | None = None
    verified_amount: Decimal | None = Field(default=None, ge=0, max_digits=20, decimal_places=4)
    currency: str | None = None

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.upper()
        if value not in SUPPORTED_CURRENCIES:
            raise ValueError("Choose a supported ISO currency code, such as INR, USD, EUR or GBP")
        return value


class CommentCreate(RequestModel):
    body: str = Field(min_length=1, max_length=4000)


class ReviewRequest(RequestModel):
    version: int = Field(ge=0)
    decision: Literal["approve", "reject", "reopen"]
    comment: str = Field(default="", max_length=4000)

    @model_validator(mode="after")
    def rejection_needs_reason(self) -> "ReviewRequest":
        if self.decision == "reject" and not self.comment:
            raise ValueError("Explain why this invoice is rejected")
        return self


class SharingUpdate(RequestModel):
    version: int = Field(ge=0)
    visibility: Literal["workspace", "restricted"]
    user_ids: list[uuid.UUID] = Field(default_factory=list, max_length=100)


class FieldCorrectionRequest(RequestModel):
    version: int = Field(ge=0)
    action: Literal["accept", "edit"]
    value: str | None = Field(default=None, max_length=4000)

    @model_validator(mode="after")
    def value_matches_action(self) -> "FieldCorrectionRequest":
        if self.action == "edit" and not self.value:
            raise ValueError("Provide the corrected value to edit this field")
        if self.action == "accept" and self.value is not None:
            raise ValueError("Accepting a field does not take a value")
        return self


class CollaboratorResponse(BaseModel):
    user_id: uuid.UUID
    email: str
    role: str


class CommentResponse(BaseModel):
    id: uuid.UUID
    author_user_id: uuid.UUID
    author_email: str
    body: str
    created_at: datetime


class GrantResponse(BaseModel):
    user_id: uuid.UUID
    email: str


class ReviewResponse(BaseModel):
    id: uuid.UUID
    actor_user_id: uuid.UUID
    actor_email: str
    decision: str
    comment: str
    created_at: datetime


class Capabilities(BaseModel):
    can_edit: bool
    can_review: bool
    can_share: bool
    can_assign: bool
    can_comment: bool


class WorkspaceResponse(BaseModel):
    document_id: uuid.UUID
    version: int
    category_id: uuid.UUID | None
    assigned_reviewer_id: uuid.UUID | None
    verified_amount: str | None
    currency: str | None
    verified_source: Literal["reviewer", "derived"] | None
    visibility: str
    comments: list[CommentResponse]
    grants: list[GrantResponse]
    reviews: list[ReviewResponse]
    capabilities: Capabilities


class CurrencyTotal(BaseModel):
    currency: str
    total: str
    pending_review: str
    approved: str
    rejected: str


class CategoryCount(BaseModel):
    id: uuid.UUID | None
    name: str
    document_count: int
    status_counts: dict[str, int] = Field(default_factory=dict)
    amounts_by_currency: list[CurrencyTotal] = Field(default_factory=list)
    excluded_amount_count: int = 0


class WorkspaceSummary(BaseModel):
    total_documents: int
    status_counts: dict[str, int]
    amounts_by_currency: list[CurrencyTotal]
    excluded_amount_count: int
    categories: list[CategoryCount]
    scope: Literal["all_accessible_documents"] = "all_accessible_documents"


class QuestionRequest(RequestModel):
    question: str = Field(min_length=3, max_length=1000)
    document_id: uuid.UUID | None = None
    category_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def single_scope(self) -> "QuestionRequest":
        if self.document_id is not None and self.category_id is not None:
            raise ValueError("Choose either an invoice or a category for this question")
        return self


class Citation(BaseModel):
    document_id: uuid.UUID
    filename: str
    field: str
    value: str
    evidence: str
    page_number: int


class QuestionResponse(BaseModel):
    supported: bool
    answer: str
    as_of: datetime
    citations: list[Citation] = Field(default_factory=list)
    summary: WorkspaceSummary | None = None


def _document(
    session: Session,
    org: Organization,
    user: User,
    membership: Membership,
    document_id: uuid.UUID,
    *,
    lock: bool = False,
) -> Document:
    query = select(Document).where(Document.org_id == org.id, Document.id == document_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    document = session.scalar(query)
    if document is None or not can_access_document(
        session, org.id, user.id, membership.role, document
    ):
        raise HTTPException(404, "Invoice not found")
    return document


def _metadata(session: Session, document: Document) -> InvoiceMetadata | None:
    return session.scalar(
        select(InvoiceMetadata).where(
            InvoiceMetadata.org_id == document.org_id,
            InvoiceMetadata.document_id == document.id,
        )
    )


def _mutable_metadata(session: Session, document: Document, version: int) -> InvoiceMetadata:
    metadata = _metadata(session, document)
    if (metadata.version if metadata else 0) != version:
        raise HTTPException(409, "Invoice changed. Refresh it before saving again.")
    if metadata is None:
        metadata = InvoiceMetadata(
            document_id=document.id, org_id=document.org_id, version=0, visibility="workspace"
        )
        session.add(metadata)
    return metadata


def _may_review(membership: Membership, user: User, metadata: InvoiceMetadata | None) -> bool:
    return membership.role == "admin" or (
        membership.role == "reviewer"
        and (metadata is None or metadata.assigned_reviewer_id in (None, user.id))
    )


def _may_share(membership: Membership, user: User, document: Document) -> bool:
    return membership.role == "admin" or (
        document.uploaded_by == user.id and membership.role in {"member", "reviewer"}
    )


def _require_admin(membership: Membership) -> None:
    if membership.role != "admin":
        raise HTTPException(403, "Administrator access required")


def _audit(
    session: Session,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    event_type: str,
    details: dict[str, object],
    document_id: uuid.UUID | None = None,
) -> None:
    session.add(
        AuditEvent(
            org_id=org_id,
            actor_user_id=user_id,
            document_id=document_id,
            event_type=event_type,
            detail_json=json.dumps(details, default=str, sort_keys=True),
            created_at=datetime.now(UTC),
        )
    )


def _workspace(
    session: Session, document: Document, user: User, membership: Membership
) -> WorkspaceResponse:
    metadata = _metadata(session, document)
    may_review = _may_review(membership, user, metadata)
    comment_rows = session.execute(
        select(InvoiceComment, User.email)
        .join(User, User.id == InvoiceComment.author_user_id)
        .where(InvoiceComment.org_id == document.org_id, InvoiceComment.document_id == document.id)
        .order_by(InvoiceComment.created_at, InvoiceComment.id)
    )
    comments = [
        CommentResponse(
            id=row.id,
            author_user_id=row.author_user_id,
            author_email=email,
            body=row.body,
            created_at=row.created_at,
        )
        for row, email in comment_rows
    ]
    review_rows = session.execute(
        select(InvoiceReview, User.email)
        .join(User, User.id == InvoiceReview.actor_user_id)
        .where(InvoiceReview.org_id == document.org_id, InvoiceReview.document_id == document.id)
        .order_by(InvoiceReview.created_at, InvoiceReview.id)
    )
    reviews = [
        ReviewResponse(
            id=row.id,
            actor_user_id=row.actor_user_id,
            actor_email=email,
            decision=row.decision,
            comment=row.comment,
            created_at=row.created_at,
        )
        for row, email in review_rows
    ]
    grant_rows = session.execute(
        select(InvoiceGrant.user_id, User.email)
        .join(User, User.id == InvoiceGrant.user_id)
        .where(InvoiceGrant.org_id == document.org_id, InvoiceGrant.document_id == document.id)
        .order_by(User.email)
    )
    return WorkspaceResponse(
        document_id=document.id,
        version=metadata.version if metadata else 0,
        category_id=metadata.category_id if metadata else None,
        assigned_reviewer_id=metadata.assigned_reviewer_id if metadata else None,
        verified_amount=str(metadata.verified_amount)
        if metadata and metadata.verified_amount is not None
        else None,
        currency=metadata.currency if metadata else None,
        verified_source=_verified_source(metadata),
        visibility=metadata.visibility if metadata else "workspace",
        comments=comments,
        grants=[GrantResponse(user_id=user_id, email=email) for user_id, email in grant_rows],
        reviews=reviews,
        capabilities=Capabilities(
            can_edit=may_review and document.status == "needs_review",
            can_review=may_review and document.status in REVIEWABLE_STATUSES,
            can_share=_may_share(membership, user, document),
            can_assign=membership.role == "admin" and document.status == "needs_review",
            can_comment=membership.role in {"admin", "reviewer", "member"},
        ),
    )


# Statuses a reviewer can act on: decide an open review, or reopen a completed one.
COMPLETED_STATUSES = frozenset(
    {"approved", "rejected", "auto_approved", "actions_pending", "completed"}
)
REVIEWABLE_STATUSES = COMPLETED_STATUSES | {"needs_review"}


def _verified_source(metadata: InvoiceMetadata | None) -> Literal["reviewer", "derived"] | None:
    if metadata is None or metadata.verified_amount is None:
        return None
    # Money verified before provenance was recorded was always entered by a reviewer.
    return "derived" if metadata.verified_source == "derived" else "reviewer"


def _finish(
    session: Session, document: Document, user: User, membership: Membership
) -> WorkspaceResponse:
    session.flush()
    response = _workspace(session, document, user, membership)
    session.commit()
    return response


@router.get("/categories", response_model=list[CategoryResponse])
def categories(context: SessionContext) -> list[CategoryResponse]:
    session, _, org, _ = context
    rows = session.scalars(
        select(InvoiceCategory)
        .where(InvoiceCategory.org_id == org.id)
        .order_by(InvoiceCategory.name_key)
    )
    return [CategoryResponse.model_validate(row) for row in rows]


@router.post("/categories", response_model=CategoryResponse, status_code=201)
def create_category(payload: CategoryCreate, context: SessionContext) -> CategoryResponse:
    session, user, org, membership = context
    _require_admin(membership)
    category = InvoiceCategory(
        org_id=org.id,
        name=payload.name,
        name_key=payload.name.casefold(),
        description=payload.description,
        active=True,
        version=1,
    )
    session.add(category)
    try:
        session.flush()
        _audit(session, org.id, user.id, "category.created", {"category_id": category.id})
        response = CategoryResponse.model_validate(category)
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(409, "A category with this name already exists") from exc
    return response


@router.post("/categories/{category_id}", response_model=CategoryResponse)
def update_category(
    category_id: uuid.UUID, payload: CategoryUpdate, context: SessionContext
) -> CategoryResponse:
    session, user, org, membership = context
    _require_admin(membership)
    category = session.scalar(
        select(InvoiceCategory)
        .where(InvoiceCategory.org_id == org.id, InvoiceCategory.id == category_id)
        .with_for_update()
    )
    if category is None:
        raise HTTPException(404, "Category not found")
    if category.version != payload.version:
        raise HTTPException(409, "Category changed. Refresh it before saving again.")
    if payload.name is not None:
        category.name, category.name_key = payload.name, payload.name.casefold()
    if payload.description is not None:
        category.description = payload.description
    if payload.active is not None:
        category.active = payload.active
    category.version += 1
    _audit(
        session,
        org.id,
        user.id,
        "category.updated",
        {
            "category_id": category.id,
            "changes": payload.model_dump(exclude_unset=True),
        },
    )
    try:
        session.flush()
        response = CategoryResponse.model_validate(category)
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(409, "A category with this name already exists") from exc
    return response


@router.get("/organization/collaborators", response_model=list[CollaboratorResponse])
def collaborators(context: SessionContext) -> list[CollaboratorResponse]:
    session, _, org, _ = context
    rows = session.execute(
        select(Membership, User.email)
        .join(User, User.id == Membership.user_id)
        .where(Membership.org_id == org.id, Membership.status == "active")
        .order_by(User.email)
    )
    return [
        CollaboratorResponse(user_id=row.user_id, email=email, role=row.role) for row, email in rows
    ]


@router.get("/documents/{document_id}/workspace", response_model=WorkspaceResponse)
def document_workspace(document_id: uuid.UUID, context: SessionContext) -> WorkspaceResponse:
    session, user, org, membership = context
    document = _document(session, org, user, membership, document_id)
    return _workspace(session, document, user, membership)


@router.post("/documents/{document_id}/metadata", response_model=WorkspaceResponse)
def update_metadata(
    document_id: uuid.UUID, payload: MetadataUpdate, context: SessionContext
) -> WorkspaceResponse:
    session, user, org, membership = context
    document = _document(session, org, user, membership, document_id, lock=True)
    metadata = _mutable_metadata(session, document, payload.version)
    if not _may_review(membership, user, metadata):
        raise HTTPException(
            403, "Only an eligible reviewer or administrator can verify this invoice"
        )
    if document.status != "needs_review":
        raise HTTPException(
            409, "Invoice must be ready for review; reopen a completed review first"
        )
    changes = payload.model_fields_set
    if "category_id" in changes and payload.category_id != metadata.category_id:
        if payload.category_id is not None:
            category = session.scalar(
                select(InvoiceCategory)
                .where(
                    InvoiceCategory.id == payload.category_id,
                    InvoiceCategory.org_id == org.id,
                )
                .with_for_update()
            )
            if category is None or not category.active:
                raise HTTPException(400, "Choose an active category in this organization")
        metadata.category_id = payload.category_id
    if "assigned_reviewer_id" in changes:
        # A reviewer may round-trip their existing assignment, but cannot change it.
        if payload.assigned_reviewer_id != metadata.assigned_reviewer_id:
            _require_admin(membership)
            if payload.assigned_reviewer_id is not None:
                assigned = session.scalar(
                    select(Membership)
                    .where(
                        Membership.org_id == org.id,
                        Membership.user_id == payload.assigned_reviewer_id,
                        Membership.status == "active",
                        Membership.role.in_(["admin", "reviewer"]),
                    )
                    .with_for_update(key_share=True, read=True)
                )
                if assigned is None:
                    raise HTTPException(400, "Choose an active reviewer in this organization")
            metadata.assigned_reviewer_id = payload.assigned_reviewer_id
    amount = payload.verified_amount if "verified_amount" in changes else metadata.verified_amount
    currency = payload.currency if "currency" in changes else metadata.currency
    if (amount is None) != (currency is None):
        raise HTTPException(422, "Verified amount and explicit currency must be provided together")
    metadata.verified_amount, metadata.currency = amount, currency
    metadata.verified_source = "reviewer" if amount is not None else None
    metadata.version += 1
    document.updated_at = datetime.now(UTC)
    _audit(
        session,
        org.id,
        user.id,
        "invoice.metadata_updated",
        {
            "document_id": document.id,
            "changes": payload.model_dump(exclude_unset=True),
        },
        document_id=document.id,
    )
    return _finish(session, document, user, membership)


@router.post("/documents/{document_id}/comments", response_model=WorkspaceResponse, status_code=201)
def add_comment(
    document_id: uuid.UUID, payload: CommentCreate, context: SessionContext
) -> WorkspaceResponse:
    session, user, org, membership = context
    document = _document(session, org, user, membership, document_id, lock=True)
    if membership.role not in {"admin", "reviewer", "member"}:
        raise HTTPException(403, "Your role can view invoices but cannot comment")
    comment = InvoiceComment(
        org_id=org.id,
        document_id=document.id,
        author_user_id=user.id,
        body=payload.body,
        created_at=datetime.now(UTC),
    )
    session.add(comment)
    session.flush()
    _audit(
        session,
        org.id,
        user.id,
        "invoice.commented",
        {
            "document_id": document.id,
            "comment_id": comment.id,
        },
        document_id=document.id,
    )
    return _finish(session, document, user, membership)


@router.post("/documents/{document_id}/review", response_model=WorkspaceResponse)
def review_invoice(
    document_id: uuid.UUID, payload: ReviewRequest, context: SessionContext
) -> WorkspaceResponse:
    session, user, org, membership = context
    document = _document(session, org, user, membership, document_id, lock=True)
    metadata = _mutable_metadata(session, document, payload.version)
    if not _may_review(membership, user, metadata):
        raise HTTPException(
            403, "Only an eligible reviewer or administrator can review this invoice"
        )
    config = review_service.pinned_config(session, document)
    approval: dict[str, object] = {}
    if payload.decision == "reopen":
        if document.status not in COMPLETED_STATUSES:
            raise HTTPException(409, "Only approved or rejected invoices can be reopened")
        new_status = "needs_review"
        review_service.open_review_task(session, org.id, document.id, config.review_sla_minutes)
        # Proposals built from the old values must not be approved later by mistake.
        actions_service.withdraw_open_actions(session, document, user.id, datetime.now(UTC))
        if metadata.verified_source == "derived":
            # Derived money reflects the fields at approval time; a reopened review
            # may change them, so the next approval derives it again.
            metadata.verified_amount, metadata.currency, metadata.verified_source = None, None, None
    else:
        if document.status != "needs_review":
            raise HTTPException(409, "Invoice is not awaiting review")
        if payload.decision == "approve":
            approval = _prepare_approval(session, org, document, metadata)
            new_status = "approved"
            # Destinations are proposed by the worker; the outbox row commits with the review.
            actions_service.enqueue_propose_actions(session, org.id, document.id)
        else:
            new_status = "rejected"
        review_service.complete_review_task(
            session, org.id, document.id, "approved" if new_status == "approved" else "rejected"
        )
    previous_status = document.status
    document.status, document.updated_at = new_status, datetime.now(UTC)
    metadata.version += 1
    session.add(
        InvoiceReview(
            org_id=org.id,
            document_id=document.id,
            actor_user_id=user.id,
            decision=payload.decision,
            comment=payload.comment,
            created_at=datetime.now(UTC),
        )
    )
    _audit(
        session,
        org.id,
        user.id,
        f"invoice.{payload.decision}",
        {
            "document_id": document.id,
            "from_status": previous_status,
            "to_status": new_status,
            "comment": payload.comment,
            "verified_amount": metadata.verified_amount,
            "currency": metadata.currency,
            **approval,
        },
        document_id=document.id,
    )
    return _finish(session, document, user, membership)


def _prepare_approval(
    session: Session, org: Organization, document: Document, metadata: InvoiceMetadata
) -> dict[str, object]:
    """Every flagged field needs a reviewer decision, and money must be verifiable.

    Returns audit detail: whether money was derived and which rules currently fail
    against the corrected values (recorded, never blocking).
    """
    unresolved = review_service.unresolved_flag_count(session, org.id, document.id)
    if unresolved:
        raise HTTPException(422, f"{unresolved} field(s) still need review")
    failed_rules = [
        rule.name
        for rule in review_service.effective_rule_results(session, document)
        if rule.passed is False
    ]
    reviewer_entered = (
        metadata.verified_amount is not None
        and metadata.currency is not None
        and metadata.verified_source != "derived"
    )
    if reviewer_entered:
        return {"derived_money": False, "failed_rules": failed_rules}
    preferred_currency = metadata.currency if metadata.verified_source == "reviewer" else None
    derived = review_service.derive_verified_money(
        session, document, org.default_currency, preferred_currency
    )
    if derived is None or derived[1] not in SUPPORTED_CURRENCIES:
        raise HTTPException(422, "Verify the invoice amount and currency before approval")
    metadata.verified_amount, metadata.currency = derived
    metadata.verified_source = "derived"
    return {"derived_money": True, "failed_rules": failed_rules}


@router.post("/documents/{document_id}/fields/{field_id}", response_model=DocumentDetail)
def correct_field(
    document_id: uuid.UUID,
    field_id: uuid.UUID,
    payload: FieldCorrectionRequest,
    context: SessionContext,
) -> DocumentDetail:
    session, user, org, membership = context
    document = _document(session, org, user, membership, document_id, lock=True)
    # Authorization before the optimistic-concurrency check: a forbidden caller
    # gets 403 rather than learning about version drift through a 409.
    if not _may_review(membership, user, _metadata(session, document)):
        raise HTTPException(
            403, "Only an eligible reviewer or administrator can correct this invoice"
        )
    metadata = _mutable_metadata(session, document, payload.version)
    if document.status != "needs_review":
        raise HTTPException(
            409, "Invoice must be ready for review; reopen a completed review first"
        )
    try:
        correction = review_service.apply_correction(
            session, document, user.id, field_id, payload.action, payload.value
        )
    except review_service.FieldNotFound as exc:
        raise HTTPException(404, str(exc)) from exc
    except review_service.InvalidCorrection as exc:
        raise HTTPException(422, str(exc)) from exc
    metadata.version += 1
    document.updated_at = datetime.now(UTC)
    _audit(
        session,
        org.id,
        user.id,
        "invoice.field_edited" if payload.action == "edit" else "invoice.field_accepted",
        {
            "document_id": document.id,
            "field": correction.field_name,
            "before": correction.before_value,
            "after": correction.after_value,
        },
        document_id=document.id,
    )
    session.flush()
    response = review_service.document_detail(session, document, (user.id, membership.role))
    session.commit()
    return response


@router.get("/review/queue", response_model=list[QueueItem])
def review_queue(
    context: SessionContext,
    document_type: Annotated[str | None, Query(max_length=50)] = None,
    vendor: Annotated[str | None, Query(min_length=1, max_length=200)] = None,
    max_age_hours: Annotated[int | None, Query(ge=1, le=24 * 365)] = None,
    assigned: Literal["me", "unassigned", "all"] = "all",
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[QueueItem]:
    session, user, org, membership = context
    return review_service.review_queue(
        session,
        org.id,
        user.id,
        membership.role,
        document_type=document_type,
        vendor=vendor,
        max_age_hours=max_age_hours,
        assigned=assigned,
        offset=offset,
        limit=limit,
    )


@router.get("/documents/{document_id}/timeline", response_model=list[TimelineEntry])
def document_timeline(document_id: uuid.UUID, context: SessionContext) -> list[TimelineEntry]:
    session, user, org, membership = context
    document = _document(session, org, user, membership, document_id)
    return review_service.timeline(session, org.id, document.id)


@router.post("/documents/{document_id}/sharing", response_model=WorkspaceResponse)
def update_sharing(
    document_id: uuid.UUID, payload: SharingUpdate, context: SessionContext
) -> WorkspaceResponse:
    session, user, org, membership = context
    document = _document(session, org, user, membership, document_id, lock=True)
    if not _may_share(membership, user, document):
        raise HTTPException(403, "Only the uploader or an administrator can manage sharing")
    metadata = _mutable_metadata(session, document, payload.version)
    desired = set(payload.user_ids)
    if desired:
        active = set(
            session.scalars(
                select(Membership.user_id)
                .where(
                    Membership.org_id == org.id,
                    Membership.user_id.in_(desired),
                    Membership.status == "active",
                )
                .with_for_update(key_share=True, read=True)
            )
        )
        if active != desired:
            raise HTTPException(400, "Sharing is limited to active members of this organization")
    session.execute(
        delete(InvoiceGrant).where(
            InvoiceGrant.org_id == org.id,
            InvoiceGrant.document_id == document.id,
        )
    )
    for target in desired:
        session.add(InvoiceGrant(org_id=org.id, document_id=document.id, user_id=target))
    metadata.visibility = payload.visibility
    metadata.version += 1
    _audit(
        session,
        org.id,
        user.id,
        "invoice.sharing_updated",
        {
            "document_id": document.id,
            "visibility": payload.visibility,
            "user_ids": sorted(str(target) for target in desired),
        },
        document_id=document.id,
    )
    return _finish(session, document, user, membership)


def _summary(
    session: Session,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    role: str,
    *,
    category_id: uuid.UUID | None = None,
) -> WorkspaceSummary:
    filters = [accessible_document_clause(org_id, user_id, role)]
    if category_id is not None:
        filters.append(InvoiceMetadata.category_id == category_id)
    joined = and_(InvoiceMetadata.document_id == Document.id, InvoiceMetadata.org_id == org_id)
    # One grouped statement gives every count and total the same database snapshot.
    rows = session.execute(
        select(
            Document.status,
            InvoiceMetadata.currency,
            InvoiceMetadata.category_id,
            InvoiceCategory.name,
            func.count(Document.id),
            func.sum(InvoiceMetadata.verified_amount),
            func.sum(
                case(
                    (
                        or_(
                            InvoiceMetadata.verified_amount.is_(None),
                            InvoiceMetadata.currency.is_(None),
                        ),
                        1,
                    ),
                    else_=0,
                )
            ),
        )
        .select_from(Document)
        .outerjoin(InvoiceMetadata, joined)
        .outerjoin(
            InvoiceCategory,
            and_(
                InvoiceCategory.id == InvoiceMetadata.category_id, InvoiceCategory.org_id == org_id
            ),
        )
        .where(*filters)
        .group_by(
            Document.status,
            InvoiceMetadata.currency,
            InvoiceMetadata.category_id,
            InvoiceCategory.name,
        )
    )
    status_counts: dict[str, int] = {}
    money: dict[str, dict[str, Decimal]] = {}
    category_counts: dict[uuid.UUID | None, CategoryCount] = {}
    category_money: dict[uuid.UUID | None, dict[str, dict[str, Decimal]]] = {}
    excluded = 0

    def accumulate_money(
        target: dict[str, dict[str, Decimal]], currency: str, amount: Decimal, state: str
    ) -> None:
        bucket = target.setdefault(
            currency,
            {key: Decimal("0.0000") for key in ("total", "pending_review", "approved", "rejected")},
        )
        bucket["total"] += amount
        status_key = {
            "needs_review": "pending_review",
            "auto_approved": "approved",
            "actions_pending": "approved",
            "completed": "approved",
        }.get(state, state)
        if status_key in {"pending_review", "approved", "rejected"}:
            bucket[status_key] += amount

    def currency_rows(target: dict[str, dict[str, Decimal]]) -> list[CurrencyTotal]:
        return [
            CurrencyTotal(currency=currency, **{key: str(value) for key, value in values.items()})
            for currency, values in sorted(target.items())
        ]

    for row in rows:
        state, currency, category, name, count, amount, missing = cast(
            tuple[str, str | None, uuid.UUID | None, str | None, int, Decimal | None, int], row
        )
        status_counts[state] = status_counts.get(state, 0) + count
        excluded += missing
        entry = category_counts.setdefault(
            category,
            CategoryCount(
                id=category,
                name=name or "Uncategorized",
                document_count=0,
            ),
        )
        entry.document_count += count
        entry.status_counts[state] = entry.status_counts.get(state, 0) + count
        entry.excluded_amount_count += missing
        if currency is not None and amount is not None:
            accumulate_money(money, currency, amount, state)
            accumulate_money(category_money.setdefault(category, {}), currency, amount, state)
    for category, entry in category_counts.items():
        entry.amounts_by_currency = currency_rows(category_money.get(category, {}))
    return WorkspaceSummary(
        total_documents=sum(status_counts.values()),
        status_counts=status_counts,
        amounts_by_currency=currency_rows(money),
        excluded_amount_count=excluded,
        categories=sorted(category_counts.values(), key=lambda entry: entry.name.casefold()),
    )


@router.get("/workspace/summary", response_model=WorkspaceSummary)
def workspace_summary(context: SessionContext) -> WorkspaceSummary:
    session, user, org, membership = context
    return _summary(session, org.id, user.id, membership.role)


def _requested_states(question: str) -> list[str]:
    return [
        state
        for pattern, state in (
            (
                r"\b(?:needs? review|pending|awaiting review|to review|for review|review needed|"
                r"unreviewed|needs? to be reviewed)\b",
                "needs_review",
            ),
            (r"\bapproved\b", "approved"),
            (r"\brejected\b", "rejected"),
            (r"\bfailed\b", "failed"),
            (r"\bqueued\b", "queued"),
            (r"\bextracting\b", "extracting"),
        )
        if re.search(pattern, question)
    ]


def _summary_answer(summary: WorkspaceSummary, question: str) -> str:
    states = _requested_states(question)
    state = states[0] if states else None
    money_requested = bool(
        re.search(r"\b(?:amounts?|totals?|sum|money|value|summary|overview)\b", question)
    )
    money_field = {
        "needs_review": "pending_review",
        "approved": "approved",
        "rejected": "rejected",
    }.get(state or "", "total")
    if state:
        count = summary.status_counts.get(state, 0)
        answer = f"{count} accessible invoice(s) have status {state.replace('_', ' ')}."
    else:
        answer = f"There are {summary.total_documents} accessible invoices."
        if summary.status_counts:
            answer += (
                " Statuses: "
                + ", ".join(
                    f"{key.replace('_', ' ')}: {value}"
                    for key, value in sorted(summary.status_counts.items())
                )
                + "."
            )
    if money_requested:
        if state in {"failed", "queued", "extracting"}:
            answer += " Verified totals are available for invoices ready for review or reviewed."
        elif summary.amounts_by_currency:
            answer += (
                " Verified amounts: "
                + ", ".join(
                    f"{item.currency} {getattr(item, money_field)}"
                    for item in summary.amounts_by_currency
                )
                + ". Currencies are reported separately."
            )
        else:
            answer += " No verified amounts with explicit currency are available."
        answer += (
            f" {summary.excluded_amount_count} invoice(s) across this scope are excluded "
            "from money totals because their amount or currency is unverified."
        )
    if re.search(r"\b(?:categor(?:y|ies)|summary|overview)\b", question):
        category_details: list[str] = []
        for item in summary.categories:
            count = item.status_counts.get(state, 0) if state else item.document_count
            detail = f"{item.name}: {count} invoice(s)"
            if money_requested and state not in {"failed", "queued", "extracting"}:
                detail += (
                    " (verified "
                    + (
                        ", ".join(
                            f"{money.currency} {getattr(money, money_field)}"
                            for money in item.amounts_by_currency
                        )
                        or "amounts unavailable"
                    )
                    + ")"
                )
            category_details.append(detail)
        answer += " Categories: " + ("; ".join(category_details) or "none") + "."
    return answer


def _known_question_words(question: str, *, document: bool = False) -> bool:
    """Refuse unimplemented filters instead of silently widening a money query."""
    common = set(
        "a an the this that these those of for in on by with all my our your me us please "
        "can could would you tell show give get what which who whose how many much is are do does "
        "have has there be been and or to from about current currently accessible workspace "
        "organization organisation company invoice invoices document documents status statuses "
        "review reviews reviewed unreviewed pending awaiting need needs needed ready "
        "approved rejected failed queued "
        "extracting amount amounts total totals sum money value verified currency currencies "
        "count counts summary summaries summarize summarise overview category categories "
        "categorized categorised grouped per each number".split()
    )
    if document:
        common.update(
            "vendor supplier seller reference date extracted evidence fields details s".split()
        )
    return set(re.findall(r"[a-z0-9]+", question)) <= common


@router.post("/workspace/questions", response_model=QuestionResponse)
def workspace_question(payload: QuestionRequest, context: SessionContext) -> QuestionResponse:
    session, user, org, membership = context
    question = payload.question.lower()
    now = datetime.now(UTC)
    if payload.document_id is not None:
        document = _document(session, org, user, membership, payload.document_id)
        metadata = _metadata(session, document)
        patterns = {
            "vendor": r"\b(?:vendor|supplier|seller)\b",
            "invoice_number": r"\b(?:number|reference)\b",
            "invoice_date": r"\bdate\b",
            "total": r"\b(?:total|amount|value)\b",
        }
        requested = [field for field, pattern in patterns.items() if re.search(pattern, question)]
        overview = bool(
            re.search(r"\b(?:summary|summarize|summarise|overview|fields|details)\b", question)
        )
        status_question = bool(
            re.search(r"\b(?:status|review|approved|rejected|category)\b", question)
        )
        if (not requested and not overview and not status_question) or not _known_question_words(
            question, document=True
        ):
            return QuestionResponse(
                supported=False,
                answer=(
                    "I can report this invoice's extracted vendor, number, date, total, evidence, "
                    "review status and category. This question needs information outside "
                    "those records."
                ),
                as_of=now,
            )
        rows = session.scalars(
            select(ExtractedField)
            .where(
                ExtractedField.org_id == org.id,
                ExtractedField.document_id == document.id,
            )
            .order_by(ExtractedField.name)
        )
        citations = [
            Citation(
                document_id=document.id,
                filename=document.filename,
                field=row.name,
                value=row.value,
                evidence=row.evidence,
                page_number=row.page_number,
            )
            for row in rows
            if overview or row.name in requested
        ]
        answer = f"{document.filename}: {document.status.replace('_', ' ')}."
        if citations:
            answer += (
                " Extracted evidence: "
                + "; ".join(
                    f"{item.field.replace('_', ' ')}: {item.value} (page {item.page_number})"
                    for item in citations
                )
                + "."
            )
        elif requested or overview:
            answer += " No matching extracted fields are available yet."
        if metadata and metadata.verified_amount is not None:
            answer += f" Verified amount: {metadata.currency} {metadata.verified_amount}."
        else:
            answer += " The amount and currency have not been verified."
        if metadata and metadata.category_id:
            category = session.scalar(
                select(InvoiceCategory).where(
                    InvoiceCategory.org_id == org.id,
                    InvoiceCategory.id == metadata.category_id,
                )
            )
            if category:
                answer += f" Category: {category.name}."
        else:
            answer += " Category: Uncategorized."
        return QuestionResponse(supported=True, answer=answer, as_of=now, citations=citations)

    category_id = payload.category_id
    if category_id is not None:
        category = session.scalar(
            select(InvoiceCategory).where(
                InvoiceCategory.org_id == org.id,
                InvoiceCategory.id == payload.category_id,
            )
        )
        if category is None:
            raise HTTPException(404, "Category not found")
    # Named categories may be used directly in a question, or supplied by the selector.
    known_categories = session.scalars(
        select(InvoiceCategory).where(InvoiceCategory.org_id == org.id)
    )
    matches = [
        item
        for item in known_categories
        if re.search(
            r"\b(?:category|for|in)\s+[\"']?" + re.escape(item.name.lower()) + r"(?!\w)", question
        )
        or re.search(r"(?<!\w)" + re.escape(item.name.lower()) + r"[\"']?\s+category\b", question)
    ]
    if len(matches) == 1 and category_id in (None, matches[0].id):
        category_id = matches[0].id
        question = re.sub(r"(?<!\w)" + re.escape(matches[0].name.lower()) + r"(?!\w)", "", question)
    elif matches:
        return QuestionResponse(
            supported=False,
            answer=(
                "Choose one category for this question. The named categories and selected scope "
                "must agree."
            ),
            as_of=now,
        )
    if len(_requested_states(question)) > 1:
        return QuestionResponse(
            supported=False,
            answer=(
                "Ask about one review status at a time, or ask for a workspace summary to see "
                "all status counts."
            ),
            as_of=now,
        )
    # Never silently ignore vendor/date filters and return an unrelated grand total.
    unsupported_filter = re.search(
        r"\b(?:vendor|supplier|before|after|between|since|last|today|yesterday|month|year|week|date)\b"
        r"|\b\d{4}-\d{2}(?:-\d{2})?\b",
        question,
    )
    supported = (
        bool(
            re.search(
                r"\b(?:counts?|how many|amounts?|totals?|sum|summary|overview|status|pending|"
                r"review|approved|"
                r"rejected|failed|queued|extracting|category|categories)\b",
                question,
            )
        )
        and not unsupported_filter
        and _known_question_words(question)
    )
    if not supported:
        return QuestionResponse(
            supported=False,
            answer=(
                "I can answer current workspace invoice counts, review statuses, verified totals "
                "by currency and category summaries. Select an invoice for vendor/date/source "
                "details, or select a category to scope a total. Date ranges and vendor filters "
                "are not supported."
            ),
            as_of=now,
        )
    summary = _summary(session, org.id, user.id, membership.role, category_id=category_id)
    return QuestionResponse(
        supported=True, answer=_summary_answer(summary, question), as_of=now, summary=summary
    )
