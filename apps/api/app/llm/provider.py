import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from io import BytesIO
from time import perf_counter
from typing import Any, Protocol

import httpx
from pypdf import PdfReader

from app.config import get_settings
from app.prompts import extraction_v2
from app.workflow_config import DocumentTypeSpec, WorkflowConfigModel


class ExtractionError(Exception):
    pass


class ProviderUnavailable(Exception):
    pass


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


class ExtractionProvider(Protocol):
    name: str
    model: str
    prompt_version: str

    def extract(self, data: bytes, config: WorkflowConfigModel) -> ExtractionResult: ...


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


def detect_document_type(pages: list[str], config: WorkflowConfigModel) -> DocumentTypeSpec:
    """Pick the first type whose detect keywords appear in the text, else the first type."""
    if len(config.document_types) == 1:
        return config.document_types[0]
    text = "\n".join(pages).casefold()
    for type_spec in config.document_types:
        if any(keyword.casefold() in text for keyword in type_spec.detect if keyword.strip()):
            return type_spec
    return config.document_types[0]


def _elapsed_ms(started: float) -> int:
    return int((perf_counter() - started) * 1000)


class RulesInvoiceProvider:
    """Extract exact "Label: value" lines from text PDFs for every configured field."""

    name = "rules"
    model = "invoice-pattern-v2"
    prompt_version = "rules-v2"

    def extract(self, data: bytes, config: WorkflowConfigModel) -> ExtractionResult:
        started = perf_counter()
        pages = pdf_pages(data)
        type_spec = detect_document_type(pages, config)
        fields: list[ExtractedValue] = []
        found: set[str] = set()
        for page_number, text in enumerate(pages, start=1):
            for line in text.splitlines():
                for spec in type_spec.fields:
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
        if not fields:
            raise ExtractionError(f"No supported {type_spec.label.lower()} fields were found")
        return ExtractionResult(
            fields=fields,
            pages=pages,
            document_type=type_spec.name,
            model=self.model,
            prompt_version=self.prompt_version,
            tokens_in=None,
            tokens_out=None,
            latency_ms=_elapsed_ms(started),
        )


class MockInvoiceProvider(RulesInvoiceProvider):
    """Deterministic provider retained for automated fixtures."""

    name = "mock"
    prompt_version = "mock-v2"


class OpenRouterInvoiceProvider:
    """Structured text extraction through OpenRouter with exact source validation."""

    name = "openrouter"
    prompt_version = extraction_v2.PROMPT_VERSION

    def __init__(self, api_key: str, model: str, client: httpx.Client | None = None) -> None:
        self.api_key = api_key
        self.model = model
        self.client = client or httpx.Client(timeout=45)

    def extract(self, data: bytes, config: WorkflowConfigModel) -> ExtractionResult:
        started = perf_counter()
        pages = pdf_pages(data)
        type_spec = detect_document_type(pages, config)
        text = "\n\n".join(f"[Page {number}]\n{page}" for number, page in enumerate(pages, 1))
        schema: dict[str, Any] = {
            "type": "object",
            "properties": {
                "fields": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {
                                "type": "string",
                                "enum": [spec.name for spec in type_spec.fields],
                            },
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
        payload = {
            "model": self.model,
            "temperature": 0,
            "max_tokens": 1200,
            "provider": {"require_parameters": True},
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "document_fields", "strict": True, "schema": schema},
            },
            "messages": [
                {"role": "system", "content": extraction_v2.render_system_prompt(type_spec)},
                {"role": "user", "content": f"<document_text>\n{text}\n</document_text>"},
            ],
        }
        try:
            response = self.client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=payload,
            )
            response.raise_for_status()
            body = response.json()
            content = body["choices"][0]["message"]["content"]
            decoded = json.loads(content)
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
            raise ProviderUnavailable("OpenRouter did not return valid structured output") from exc

        usage = body.get("usage") if isinstance(body, dict) else None
        tokens_in = _token_count(usage, "prompt_tokens")
        tokens_out = _token_count(usage, "completion_tokens")
        rows = decoded.get("fields") if isinstance(decoded, dict) else None
        if not isinstance(rows, list) or not rows:
            raise ExtractionError("No supported document fields were returned")
        known = {spec.name for spec in type_spec.fields}
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
        if not fields:
            raise ExtractionError("OpenRouter returned no field with matching PDF evidence")
        return ExtractionResult(
            fields=fields,
            pages=pages,
            document_type=type_spec.name,
            model=self.model,
            prompt_version=self.prompt_version,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            latency_ms=_elapsed_ms(started),
            notes=notes,
        )


def _token_count(usage: object, key: str) -> int | None:
    if isinstance(usage, dict):
        value = usage.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            return value
    return None


@lru_cache
def get_provider() -> ExtractionProvider:
    settings = get_settings()
    if settings.llm_provider == "rules":
        return RulesInvoiceProvider()
    if settings.llm_provider == "mock":
        return MockInvoiceProvider()
    if settings.llm_provider == "openrouter":
        if not settings.openrouter_api_key:
            raise RuntimeError("OPENROUTER_API_KEY is required for the OpenRouter worker")
        return OpenRouterInvoiceProvider(settings.openrouter_api_key, settings.openrouter_model)
    raise RuntimeError(f"Unknown LLM_PROVIDER: {settings.llm_provider}")
