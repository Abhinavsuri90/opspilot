"""Per-organization memory: vendor profiles and few-shot examples learned from reviewers.

Every edit a reviewer makes, and every approval, updates the vendor's profile (typical
currency, the format pattern of each field's values, the last values seen) and stores the
edit as a few-shot example. At extraction time the worker loads the profiles whose vendor
appears in the page text and the three most relevant examples (same vendor first, then
cosine similarity between the example's text and the page text); the examples go into
the OpenRouter prompt and the profile feeds the ``memory_prior`` confidence signal.

Rows live in ``memory_items`` behind row-level security and every query here is scoped
by ``org_id``; nothing in memory is ever shared between organizations. Design notes:
docs/adr/009-learning-loop-and-router.md.
"""

from __future__ import annotations

import json
import re
import uuid
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import lru_cache

from sqlalchemy.orm import Session

from app.config import get_settings
from app.learning_models import MemoryItem
from app.llm import budget
from app.llm.embeddings import Embedder, LocalHashEmbedder, RemoteEmbedder, cosine_similarity
from app.llm.provider import ExtractedValue, detect_document_type
from app.prompts.extraction_v3 import FewShotExample
from app.repositories import (
    get_vendor_profile,
    list_few_shots,
    list_few_shots_by_similarity,
    list_vendor_profile_keys,
    list_vendor_profiles,
)
from app.workflow_config import DocumentTypeSpec, WorkflowConfigModel

FEW_SHOT_LIMIT = 3
MAX_FEW_SHOTS_PER_VENDOR = 20
MAX_PROFILE_PATTERNS = 8
MAX_SNIPPET_CHARS = 240
MAX_VALUE_CHARS = 200
MAX_PAGE_CHARS = 6000
MAX_PROFILE_KEYS = 500
_WHITESPACE = re.compile(r"\s+")
_KEY_STRIP = re.compile(r"[^\w\s]")


def normalize_vendor(name: str) -> str:
    """Casefolded, punctuation-free, whitespace-collapsed vendor name used as the key."""
    return _WHITESPACE.sub(" ", _KEY_STRIP.sub(" ", name.casefold())).strip()[:200]


def format_pattern(value: str) -> str:
    """Digits become 9 and letters A; punctuation and spacing stay ("05-Mar-26" -> "99-AAA-99")."""
    return "".join(
        "9" if char.isdigit() else "A" if char.isalpha() else char for char in value.strip()
    )


@dataclass
class VendorProfile:
    key: str
    name: str
    typical_currency: str | None = None
    currency_counts: dict[str, int] = field(default_factory=dict)
    # field name -> pattern -> times seen
    patterns: dict[str, dict[str, int]] = field(default_factory=dict)
    last_values: dict[str, str] = field(default_factory=dict)
    documents: int = 0

    def to_json(self) -> str:
        return json.dumps(
            {
                "name": self.name,
                "typical_currency": self.typical_currency,
                "currency_counts": self.currency_counts,
                "patterns": self.patterns,
                "last_values": self.last_values,
                "documents": self.documents,
            },
            sort_keys=True,
        )

    @classmethod
    def from_row(cls, row: MemoryItem) -> VendorProfile:
        try:
            raw = json.loads(row.content_json)
        except ValueError:
            raw = {}
        data = raw if isinstance(raw, dict) else {}
        patterns = data.get("patterns")
        counts = data.get("currency_counts")
        last = data.get("last_values")
        return cls(
            key=row.key,
            name=str(data.get("name") or row.key),
            typical_currency=(
                str(data["typical_currency"]) if data.get("typical_currency") else None
            ),
            currency_counts=(
                {str(k): int(v) for k, v in counts.items()} if isinstance(counts, dict) else {}
            ),
            patterns=(
                {
                    str(name): {str(p): int(n) for p, n in inner.items()}
                    for name, inner in patterns.items()
                    if isinstance(inner, dict)
                }
                if isinstance(patterns, dict)
                else {}
            ),
            last_values={str(k): str(v) for k, v in last.items()} if isinstance(last, dict) else {},
            documents=int(data.get("documents") or 0),
        )

    def absorb(self, values: Mapping[str, str], type_spec: DocumentTypeSpec) -> None:
        """Fold one document's confirmed values into the profile."""
        self.documents += 1
        for spec in type_spec.fields:
            value = (values.get(spec.name) or "").strip()
            if not value:
                continue
            if spec.type == "currency":
                code = value.upper()
                self.currency_counts[code] = self.currency_counts.get(code, 0) + 1
                self.typical_currency = Counter(self.currency_counts).most_common(1)[0][0]
            pattern = format_pattern(value)
            seen = self.patterns.setdefault(spec.name, {})
            seen[pattern] = seen.get(pattern, 0) + 1
            if len(seen) > MAX_PROFILE_PATTERNS:
                rarest = min(seen.items(), key=lambda item: (item[1], item[0]))[0]
                del seen[rarest]
            self.last_values[spec.name] = value[:MAX_VALUE_CHARS]


def prior_for(profile: VendorProfile | None, spec_type: str, name: str, value: str) -> float | None:
    """The memory_prior signal: currency 1.0/0.3, other fields 1.0/0.5, None without data."""
    if profile is None:
        return None
    if spec_type == "currency":
        if profile.typical_currency is None:
            return None
        return 1.0 if value.strip().upper() == profile.typical_currency else 0.3
    known = profile.patterns.get(name)
    if not known:
        return None
    return 1.0 if format_pattern(value) in known else 0.5


def priors_for(
    profile: VendorProfile | None, type_spec: DocumentTypeSpec, fields: Iterable[ExtractedValue]
) -> dict[str, float | None]:
    priors: dict[str, float | None] = {}
    for extracted in fields:
        spec = type_spec.field(extracted.name)
        if spec is None:
            continue
        priors[extracted.name] = prior_for(profile, spec.type, extracted.name, extracted.value)
    return priors


@dataclass(frozen=True)
class Correction:
    field: str
    wrong_value: str
    correct_value: str
    evidence: str


@dataclass
class MemoryContext:
    """What the worker loaded for one document before extraction."""

    examples: list[FewShotExample] = field(default_factory=list)
    profiles: dict[str, VendorProfile] = field(default_factory=dict)
    detected_vendor: str | None = None

    def profile_for(self, vendor_value: str | None) -> VendorProfile | None:
        """The extracted vendor's profile, else the one whose name appeared in the text."""
        if vendor_value:
            match = self.profiles.get(normalize_vendor(vendor_value))
            if match is not None:
                return match
        if self.detected_vendor is not None:
            return self.profiles.get(self.detected_vendor)
        return None


EMPTY_CONTEXT = MemoryContext()


@lru_cache
def get_embedder() -> Embedder:
    settings = get_settings()
    if settings.embeddings_base_url and settings.embeddings_model:
        return RemoteEmbedder(
            settings.embeddings_base_url,
            settings.embeddings_model,
            settings.embeddings_api_key,
            allow_paid_call=budget.allows_for_org,
        )
    return LocalHashEmbedder()


def _few_shot_from_row(row: MemoryItem) -> FewShotExample | None:
    try:
        raw = json.loads(row.content_json)
    except ValueError:
        return None
    if not isinstance(raw, dict):
        return None
    return FewShotExample(
        vendor=str(raw.get("vendor") or row.key),
        field=str(raw.get("field") or ""),
        wrong_value=str(raw.get("wrong_value") or ""),
        correct_value=str(raw.get("correct_value") or ""),
        snippet=str(raw.get("snippet") or ""),
    )


def detect_vendor(page_text: str, keys: Sequence[str]) -> str | None:
    """The longest known vendor key that appears in the normalized page text."""
    haystack = f" {normalize_vendor(page_text)} "
    matches = [key for key in keys if key and f" {key} " in haystack]
    return max(matches, key=len) if matches else None


def context_for(
    session: Session,
    org_id: uuid.UUID,
    pages: Sequence[str],
    config: WorkflowConfigModel,
    *,
    embedder: Embedder | None = None,
    document_id: uuid.UUID | None = None,
    trace_id: str | None = None,
    limit: int = FEW_SHOT_LIMIT,
) -> MemoryContext:
    """Profiles and few-shots relevant to this page text, all scoped to ``org_id``."""
    page_text = "\n".join(pages)[:MAX_PAGE_CHARS]
    keys = list_vendor_profile_keys(session, org_id, MAX_PROFILE_KEYS)
    detected = detect_vendor(page_text, keys)
    profiles = {
        row.key: VendorProfile.from_row(row)
        for row in list_vendor_profiles(session, org_id, [detected] if detected else [])
    }
    embedder = embedder or get_embedder()
    query = embedder.embed(page_text, org_id=org_id, document_id=document_id, trace_id=trace_id)
    if session.get_bind().dialect.name == "postgresql":
        rows = list_few_shots_by_similarity(session, org_id, detected, query, limit)
    else:
        rows = rank_in_python(list_few_shots(session, org_id), detected, query, limit)
    examples = [example for example in (_few_shot_from_row(row) for row in rows) if example]
    type_spec = detect_document_type(list(pages), config)
    examples = [example for example in examples if type_spec.field(example.field) is not None]
    return MemoryContext(examples=examples, profiles=profiles, detected_vendor=detected)


def rank_in_python(
    rows: Sequence[MemoryItem], vendor_key: str | None, query: list[float] | None, limit: int
) -> list[MemoryItem]:
    """The SQLite equivalent of the pgvector ordering: vendor match, then cosine, then recency."""

    def sort_key(row: MemoryItem) -> tuple[int, float, float]:
        similarity = (
            cosine_similarity(query, row.embedding)
            if query is not None and row.embedding is not None
            else -1.0
        )
        stamp = row.updated_at.timestamp() if row.updated_at is not None else 0.0
        return (0 if vendor_key is not None and row.key == vendor_key else 1, -similarity, -stamp)

    return sorted(rows, key=sort_key)[:limit]


def learn(
    session: Session,
    org_id: uuid.UUID,
    *,
    vendor: str,
    type_spec: DocumentTypeSpec,
    values: Mapping[str, str],
    corrections: Sequence[Correction] = (),
    embedder: Embedder | None = None,
    document_id: uuid.UUID | None = None,
    trace_id: str | None = None,
    now: datetime | None = None,
) -> tuple[VendorProfile, int]:
    """Upsert the vendor profile from confirmed values and store each correction as a few-shot.

    Returns the profile and the number of few-shot rows written (new or refreshed).
    """
    now = now or datetime.now(UTC)
    key = normalize_vendor(vendor)
    if not key:
        raise ValueError("A vendor name is required to update memory")
    row = get_vendor_profile(session, org_id, key, lock=True)
    profile = VendorProfile.from_row(row) if row is not None else VendorProfile(key, vendor.strip())
    profile.name = vendor.strip()[:MAX_VALUE_CHARS]
    profile.absorb(values, type_spec)
    if row is None:
        session.add(
            MemoryItem(
                id=uuid.uuid4(),
                org_id=org_id,
                kind="vendor_profile",
                key=key,
                content_json=profile.to_json(),
                embedding=None,
                updated_at=now,
            )
        )
    else:
        row.content_json = profile.to_json()
        row.updated_at = now
    written = 0
    if corrections:
        embedder = embedder or get_embedder()
        existing = list_few_shots(session, org_id, key)
        evidence_text = " ".join(
            f"{name}: {value}" for name, value in values.items() if value
        )
        for correction in corrections:
            if type_spec.field(correction.field) is None:
                continue
            content = {
                "vendor": profile.name,
                "field": correction.field,
                "wrong_value": correction.wrong_value.strip()[:MAX_VALUE_CHARS],
                "correct_value": correction.correct_value.strip()[:MAX_VALUE_CHARS],
                "snippet": " ".join(correction.evidence.split())[:MAX_SNIPPET_CHARS],
                "document_type": type_spec.name,
            }
            payload = json.dumps(content, sort_keys=True)
            text = f"{vendor}\n{correction.evidence}\n{evidence_text}"
            vector = embedder.embed(
                text, org_id=org_id, document_id=document_id, trace_id=trace_id
            )
            signature = _few_shot_signature(content)
            duplicate = next(
                (item for item in existing if _few_shot_signature(item.content_json) == signature),
                None,
            )
            if duplicate is not None:
                duplicate.content_json = payload
                duplicate.updated_at = now
                duplicate.embedding = vector if vector is not None else duplicate.embedding
            elif len(existing) >= MAX_FEW_SHOTS_PER_VENDOR:
                oldest = min(existing, key=lambda item: (item.updated_at, item.id))
                oldest.content_json, oldest.embedding, oldest.updated_at = payload, vector, now
            else:
                item = MemoryItem(
                    id=uuid.uuid4(),
                    org_id=org_id,
                    kind="few_shot",
                    key=key,
                    content_json=payload,
                    embedding=vector,
                    updated_at=now,
                )
                session.add(item)
                existing.append(item)
            written += 1
    session.flush()
    return profile, written


def _few_shot_signature(content: Mapping[str, object] | str) -> tuple[str, str, str]:
    """What makes two examples the same correction: the field and the before/after values."""
    if isinstance(content, str):
        try:
            decoded = json.loads(content)
        except ValueError:
            decoded = {}
        content = decoded if isinstance(decoded, dict) else {}
    return (
        str(content.get("field") or ""),
        str(content.get("wrong_value") or ""),
        str(content.get("correct_value") or ""),
    )


def learn_from_review(
    session: Session,
    org_id: uuid.UUID,
    *,
    document_id: uuid.UUID,
    trace_id: str | None,
    type_spec: DocumentTypeSpec,
    current_values: Mapping[str, str],
    evidence: Mapping[str, str],
    corrections: Sequence[tuple[str, str, str]],
    now: datetime | None = None,
) -> int:
    """Learning-loop entry point for the review API: values are the effective (corrected) ones.

    ``corrections`` are ``(field, before, after)`` edit triples. Returns the few-shots written;
    zero when the document has no counterparty value to key the memory on.
    """
    party = type_spec.party_field()
    vendor = (current_values.get(party.name) or "").strip() if party is not None else ""
    if not vendor:
        return 0
    _, written = learn(
        session,
        org_id,
        vendor=vendor,
        type_spec=type_spec,
        values=current_values,
        corrections=[
            Correction(name, before, after, evidence.get(name, ""))
            for name, before, after in corrections
            if before.strip() != after.strip()
        ],
        document_id=document_id,
        trace_id=trace_id,
        now=now,
    )
    return written


def profile_for_vendor(session: Session, org_id: uuid.UUID, vendor: str) -> VendorProfile | None:
    row = get_vendor_profile(session, org_id, normalize_vendor(vendor))
    return VendorProfile.from_row(row) if row is not None else None
