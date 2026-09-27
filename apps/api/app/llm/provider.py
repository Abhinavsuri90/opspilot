"""Extraction providers: deterministic rules and OpenRouter structured output.

Every provider extracts from parsed page text (``extract_pages``) so the router can run a
second, restricted pass over failing fields without re-parsing the PDF, and every run is
written to the ``llm_calls`` ledger through ``app.llm.client`` (the rules provider at zero
cost). ``extract`` remains the convenience path that parses the PDF first.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from functools import lru_cache
from io import BytesIO
from time import perf_counter
from typing import Any, Protocol

import httpx
from pypdf import PdfReader

from app.config import get_settings
from app.llm.client import (
    OpenRouterBackend,
    ProviderUnavailable,
    Purpose,
    Recorder,
    call_chat,
    record_local_call,
    record_to_database,
)
from app.prompts import extraction_v3
from app.prompts.extraction_v3 import FewShotExample
from app.workflow_config import DocumentTypeSpec, WorkflowConfigModel

__all__ = [
    "ExtractedValue",
    "ExtractionContext",
    "ExtractionError",
    "ExtractionProvider",
    "ExtractionResult",
    "FewShotExample",
    "MockInvoiceProvider",
    "OpenRouterInvoiceProvider",
    "ProviderUnavailable",
    "RulesInvoiceProvider",
    "detect_document_type",
    "detection_score",
    "get_provider",
    "get_tier2_provider",
    "heading_of",
    "pdf_pages",
]


class ExtractionError(Exception):
    pass


@dataclass(frozen=True)
class ExtractionContext:
    """Who the extraction is for; ledger rows carry these ids."""

    org_id: uuid.UUID | None = None
    document_id: uuid.UUID | None = None
    trace_id: str | None = None


@dataclass(frozen=True)
class ExtractedValue:
    name: str
    value: str
    evidence: str
    page_number: int
    self_confidence: float | None = None


@dataclass(frozen=True)
class ExtractionResult:
    fields: list[ExtractedValue]
    pages: list[str]
    document_type: str
    model: str
    prompt_version: str
    tokens_in: int | None
    tokens_out: int | None
    latency_ms: int
    # Fields the provider returned but could not ground in the page text.
    notes: list[str] = field(default_factory=list)
    # Cost of the calls behind this result; zero for local providers, None when unpriced.
    cost_cents: Decimal | None = Decimal("0.0000")


class ExtractionProvider(Protocol):
    name: str
    model: str
    prompt_version: str
    # Whether calls spend money, which is what the daily budget guards.
    paid: bool

    def extract(
        self, data: bytes, config: WorkflowConfigModel, context: ExtractionContext | None = None
    ) -> ExtractionResult: ...

    def extract_pages(
        self,
        pages: list[str],
        config: WorkflowConfigModel,
        context: ExtractionContext | None = None,
        *,
        document_type: str | None = None,
        field_names: Sequence[str] | None = None,
        examples: Sequence[FewShotExample] = (),
    ) -> ExtractionResult: ...


def pdf_pages(data: bytes) -> list[str]:
    try:
        reader = PdfReader(BytesIO(data), strict=False)
        if reader.is_encrypted or len(reader.pages) > 10:
            raise ExtractionError("Only unencrypted PDFs of up to 10 pages are supported")
        pages = [page.extract_text() or "" for page in reader.pages]
    except ExtractionError:
        raise
    except Exception as exc:
        raise ExtractionError("Could not read this PDF") from exc
    if not any(page.strip() for page in pages):
        raise ExtractionError("This PDF has no text layer; scanned files need OCR")
    if sum(len(page) for page in pages) > 50_000:
        raise ExtractionError("This PDF has too much text for the 50,000 character limit")
    return pages


# Extra weight for a keyword on the first line of text, which is usually the title.
HEADING_BONUS = 2


def heading_of(pages: list[str]) -> str:
    for page in pages:
        for line in page.splitlines():
            if line.strip():
                return line.casefold()
    return ""


def detection_score(pages: list[str], type_spec: DocumentTypeSpec) -> int:
    """Occurrences of the type's detect keywords, with a bonus when one is in the heading.

    Counting occurrences (rather than the first hit) keeps a delivery note that mentions a
    "PO Number" from being read as a purchase order; the heading bonus breaks ties in favour
    of the document title.
    """
    text = "\n".join(pages).casefold()
    heading = heading_of(pages)
    score = 0
    for keyword in type_spec.detect:
        needle = keyword.casefold().strip()
        if not needle:
            continue
        score += text.count(needle)
        if needle in heading:
            score += HEADING_BONUS
    return score


def detect_document_type(pages: list[str], config: WorkflowConfigModel) -> DocumentTypeSpec:
    """Pick the type whose detect keywords match best; ties and no match go to the first type."""
    if len(config.document_types) == 1:
        return config.document_types[0]
    best = config.document_types[0]
    best_score = 0
    for type_spec in config.document_types:
        score = detection_score(pages, type_spec)
        if score > best_score:
            best, best_score = type_spec, score
    return best


def resolve_type(
    pages: list[str], config: WorkflowConfigModel, document_type: str | None
) -> DocumentTypeSpec:
    """The named type when the caller already detected it, else keyword detection."""
    if document_type is not None:
        known = config.document_type(document_type)
        if known is not None:
            return known
    return detect_document_type(pages, config)


def _elapsed_ms(started: float) -> int:
    return int((perf_counter() - started) * 1000)


def _context(context: ExtractionContext | None) -> ExtractionContext:
    return context or ExtractionContext()


class RulesInvoiceProvider:
    """Extract exact "Label: value" lines from text PDFs for every configured field."""

    name = "rules"
    model = "invoice-pattern-v2"
    prompt_version = "rules-v2"
    paid = False

    def __init__(self, recorder: Recorder = record_to_database) -> None:
        self.recorder = recorder

    def extract(
        self, data: bytes, config: WorkflowConfigModel, context: ExtractionContext | None = None
    ) -> ExtractionResult:
        return self.extract_pages(pdf_pages(data), config, context)

    def extract_pages(
        self,
        pages: list[str],
        config: WorkflowConfigModel,
        context: ExtractionContext | None = None,
        *,
        document_type: str | None = None,
        field_names: Sequence[str] | None = None,
        examples: Sequence[FewShotExample] = (),
    ) -> ExtractionResult:
        started = perf_counter()
        ids = _context(context)
        type_spec = resolve_type(pages, config, document_type)
        wanted = [
            spec for spec in type_spec.fields if field_names is None or spec.name in field_names
        ]
        fields: list[ExtractedValue] = []
        found: set[str] = set()
        for page_number, text in enumerate(pages, start=1):
            for line in text.splitlines():
                for spec in wanted:
                    if spec.name in found:
                        continue
                    match = re.fullmatch(rf"\s*{re.escape(spec.label)}:\s*(.*?)\s*", line, re.I)
                    if match and match.group(1):
                        found.add(spec.name)
                        fields.append(
                            ExtractedValue(
                                name=spec.name,
                                value=match.group(1),
                                evidence=line.strip(),
                                page_number=page_number,
                                self_confidence=1.0,
                            )
                        )
        purpose: Purpose = "escalation" if field_names is not None else "extraction"
        if not fields and field_names is None:
            labels = ", ".join(spec.label for spec in type_spec.fields)
            error = (
                f"No supported {type_spec.label.lower()} fields were found "
                f"(detected type: {type_spec.name}; expected lines such as {labels})"
            )
            record_local_call(
                purpose,
                self.name,
                self.model,
                self.prompt_version,
                ids.org_id,
                ids.document_id,
                ids.trace_id,
                latency_ms=_elapsed_ms(started),
                ok=False,
                error=error,
                recorder=self.recorder,
            )
            raise ExtractionError(error)
        latency_ms = _elapsed_ms(started)
        record_local_call(
            purpose,
            self.name,
            self.model,
            self.prompt_version,
            ids.org_id,
            ids.document_id,
            ids.trace_id,
            latency_ms=latency_ms,
            ok=True,
            recorder=self.recorder,
        )
        return ExtractionResult(
            fields=fields,
            pages=pages,
            document_type=type_spec.name,
            model=self.model,
            prompt_version=self.prompt_version,
            tokens_in=None,
            tokens_out=None,
            latency_ms=latency_ms,
        )


class MockInvoiceProvider(RulesInvoiceProvider):
    """Deterministic provider retained for automated fixtures."""

    name = "mock"
    prompt_version = "mock-v2"


def field_schema(type_spec: DocumentTypeSpec, field_names: Sequence[str] | None) -> dict[str, Any]:
    names = [
        spec.name for spec in type_spec.fields if field_names is None or spec.name in field_names
    ]
    return {
        "type": "object",
        "properties": {
            "fields": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "enum": names},
                        "value": {"type": "string"},
                        "evidence": {"type": "string"},
                        "page_number": {"type": "integer"},
                        "confidence": {"type": "number"},
                    },
                    "required": ["name", "value", "evidence", "page_number", "confidence"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["fields"],
        "additionalProperties": False,
    }


class OpenRouterInvoiceProvider:
    """Structured text extraction through OpenRouter with exact source validation."""

    name = "openrouter"
    prompt_version = extraction_v3.PROMPT_VERSION
    paid = True

    def __init__(
        self,
        api_key: str,
        model: str,
        client: httpx.Client | None = None,
        *,
        recorder: Recorder = record_to_database,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.backend = OpenRouterBackend(api_key, client)
        self.recorder = recorder

    def extract(
        self, data: bytes, config: WorkflowConfigModel, context: ExtractionContext | None = None
    ) -> ExtractionResult:
        return self.extract_pages(pdf_pages(data), config, context)

    def extract_pages(
        self,
        pages: list[str],
        config: WorkflowConfigModel,
        context: ExtractionContext | None = None,
        *,
        document_type: str | None = None,
        field_names: Sequence[str] | None = None,
        examples: Sequence[FewShotExample] = (),
    ) -> ExtractionResult:
        started = perf_counter()
        ids = _context(context)
        type_spec = resolve_type(pages, config, document_type)
        text = "\n\n".join(f"[Page {number}]\n{page}" for number, page in enumerate(pages, 1))
        result = call_chat(
            "escalation" if field_names is not None else "extraction",
            [
                {
                    "role": "system",
                    "content": extraction_v3.render_system_prompt(type_spec, examples, field_names),
                },
                {"role": "user", "content": f"<document_text>\n{text}\n</document_text>"},
            ],
            field_schema(type_spec, field_names),
            self.model,
            ids.org_id,
            ids.document_id,
            ids.trace_id,
            backend=self.backend,
            prompt_version=self.prompt_version,
            recorder=self.recorder,
        )
        decoded = result.decoded
        rows = decoded.get("fields") if isinstance(decoded, dict) else None
        if not isinstance(rows, list) or not rows:
            if field_names is not None:
                rows = []
            else:
                raise ExtractionError("No supported document fields were returned")
        known = {
            spec.name
            for spec in type_spec.fields
            if field_names is None or spec.name in field_names
        }
        fields: list[ExtractedValue] = []
        notes: list[str] = []
        seen: set[str] = set()
        for row in rows:
            if not isinstance(row, dict):
                raise ExtractionError("OpenRouter returned an invalid field")
            name = row.get("name")
            if not isinstance(name, str) or name not in known or name in seen:
                notes.append(f"Dropped unknown or repeated field {name!r}")
                continue
            value, evidence = row.get("value"), row.get("evidence")
            page_number = row.get("page_number")
            if (
                not isinstance(value, str)
                or not value
                or not isinstance(evidence, str)
                or not evidence
                or not isinstance(page_number, int)
                or isinstance(page_number, bool)
                or not 1 <= page_number <= len(pages)
                or evidence not in pages[page_number - 1]
                or value not in evidence
            ):
                # One ungrounded field must not discard the grounded ones; the
                # review queue shows the gap as a missing field instead.
                notes.append(f"Dropped field '{name}': evidence not found verbatim in the PDF")
                continue
            confidence = row.get("confidence")
            self_confidence = (
                min(1.0, max(0.0, float(confidence)))
                if isinstance(confidence, int | float) and not isinstance(confidence, bool)
                else None
            )
            seen.add(name)
            fields.append(ExtractedValue(name, value, evidence, page_number, self_confidence))
        if not fields and field_names is None:
            raise ExtractionError("OpenRouter returned no field with matching PDF evidence")
        return ExtractionResult(
            fields=fields,
            pages=pages,
            document_type=type_spec.name,
            model=self.model,
            prompt_version=self.prompt_version,
            tokens_in=result.tokens_in,
            tokens_out=result.tokens_out,
            latency_ms=_elapsed_ms(started),
            notes=notes,
            cost_cents=result.cost_cents,
        )


@lru_cache
def get_provider() -> ExtractionProvider:
    """The tier-1 provider: rules, mock, or OpenRouter with LLM_TIER1_MODEL/OPENROUTER_MODEL."""
    settings = get_settings()
    if settings.llm_provider == "rules":
        return RulesInvoiceProvider()
    if settings.llm_provider == "mock":
        return MockInvoiceProvider()
    if settings.llm_provider == "openrouter":
        if not settings.openrouter_api_key:
            raise RuntimeError("OPENROUTER_API_KEY is required for the OpenRouter worker")
        model = settings.llm_tier1_model or settings.openrouter_model
        return OpenRouterInvoiceProvider(settings.openrouter_api_key, model)
    raise RuntimeError(f"Unknown LLM_PROVIDER: {settings.llm_provider}")


@lru_cache
def get_tier2_provider() -> ExtractionProvider | None:
    """The escalation provider, only for OpenRouter deployments that set LLM_TIER2_MODEL."""
    settings = get_settings()
    if settings.llm_provider != "openrouter" or not settings.llm_tier2_model:
        return None
    if not settings.openrouter_api_key:
        raise RuntimeError("OPENROUTER_API_KEY is required for the OpenRouter worker")
    return OpenRouterInvoiceProvider(settings.openrouter_api_key, settings.llm_tier2_model)
