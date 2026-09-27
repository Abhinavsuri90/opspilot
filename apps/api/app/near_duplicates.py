"""Near-duplicate detection: same counterparty, same document number, same total.

Exact duplicates never get past upload (the content hash is unique per tenant). A vendor
that re-sends an invoice as a fresh PDF, or a scan of the same purchase order, has a
different hash but the same business identity. After extraction the worker compares the new
document's (vendor or supplier, primary identifier, total) with other documents of the same
tenant and type, using the other documents' effective (corrected) values. A match links the
documents both ways, adds a reason to the identifier field and forces human review.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.confidence import Evaluation, parse_money
from app.intake_models import DocumentLink
from app.models import Document
from app.repositories import list_document_links
from app.review_service import effective_fields, effective_value_subquery
from app.workflow_config import DocumentTypeSpec

MAX_CANDIDATES = 20
LINK_KIND = "near_duplicate"
# Documents that never produced trusted values are not compared against.
EXCLUDED_STATUSES = ("queued", "extracting", "validating", "failed")


def normalize_text(value: str | None) -> str:
    return " ".join((value or "").split()).casefold()


def normalized_sql(session: Session, column: ColumnElement[Any]) -> ColumnElement[Any]:
    """The SQL side of :func:`normalize_text`: lower case, trimmed, inner whitespace collapsed.

    Postgres does the whole job; SQLite has no regexp_replace, so it lowercases and trims and
    the Python comparison on the candidate's effective values applies the full rule.
    """
    lowered = func.lower(func.trim(column))
    if session.get_bind().dialect.name == "postgresql":
        return func.regexp_replace(lowered, r"\s+", " ", "g")
    return lowered


def normalize_money(value: str | None) -> Decimal | None:
    if not value:
        return None
    amount = parse_money(value)
    return amount.normalize() if amount is not None else None


def find_near_duplicates(
    session: Session, document: Document, type_spec: DocumentTypeSpec, values: dict[str, str]
) -> list[Document]:
    """Other documents of the same tenant and type with the same identity triple."""
    identifier = type_spec.primary_identifier()
    if identifier is None:
        return []
    number = normalize_text(values.get(identifier.name))
    if not number:
        return []
    org_id = document.org_id
    stored_number = effective_value_subquery(org_id, identifier.name)
    candidates = list(
        session.scalars(
            select(Document)
            .where(
                Document.org_id == org_id,
                Document.document_type == document.document_type,
                Document.id != document.id,
                Document.status.not_in(EXCLUDED_STATUSES),
                normalized_sql(session, stored_number) == number,
            )
            .order_by(Document.created_at, Document.id)
            .limit(MAX_CANDIDATES)
        )
    )
    party = type_spec.party_field()
    compares_total = type_spec.field("total") is not None
    matches = []
    for candidate in candidates:
        effective = {
            item.field.name: item.current_value
            for item in effective_fields(session, org_id, candidate.id)
        }
        if normalize_text(effective.get(identifier.name)) != number:
            continue
        if party is not None and normalize_text(effective.get(party.name)) != normalize_text(
            values.get(party.name)
        ):
            continue
        if compares_total and normalize_money(effective.get("total")) != normalize_money(
            values.get("total")
        ):
            continue
        matches.append(candidate)
    return matches


def link_near_duplicates(
    session: Session, document: Document, matches: list[Document], now: datetime
) -> list[DocumentLink]:
    """Record the relation in both directions, skipping pairs that are already linked."""
    existing = {
        (link.document_id, link.related_document_id)
        for match in [document, *matches]
        for link in list_document_links(session, document.org_id, match.id)
        if link.kind == LINK_KIND
    }
    created: list[DocumentLink] = []
    for match in matches:
        for source, target in ((document.id, match.id), (match.id, document.id)):
            if (source, target) in existing:
                continue
            link = DocumentLink(
                id=uuid.uuid4(),
                org_id=document.org_id,
                document_id=source,
                related_document_id=target,
                kind=LINK_KIND,
                created_at=now,
            )
            session.add(link)
            created.append(link)
            existing.add((source, target))
    return created


def flag_near_duplicates(
    session: Session,
    document: Document,
    type_spec: DocumentTypeSpec,
    evaluation: Evaluation,
    now: datetime,
) -> list[Document]:
    """Find, link and flag; the identifier field is sent to review with the reason.

    The reason names no file: the earlier document may be restricted from some reviewers,
    and the viewer-filtered ``near_duplicates`` list on the document detail is where names
    belong.
    """
    values = {item.name: item.value for item in evaluation.fields}
    matches = find_near_duplicates(session, document, type_spec, values)
    if not matches:
        return []
    link_near_duplicates(session, document, matches, now)
    identifier = type_spec.primary_identifier()
    for assessment in evaluation.fields:
        if identifier is not None and assessment.name == identifier.name:
            assessment.reasons.append(duplicate_reason(type_spec))
            assessment.status = "needs_review"
    return matches


def duplicate_reason(type_spec: DocumentTypeSpec) -> str:
    return f"Possible duplicate of an earlier {type_spec.label.lower()}"
