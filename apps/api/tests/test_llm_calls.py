"""The model-call ledger: rows on success and failure, cost math, prices and the timeline."""

import json
import logging
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx
import pytest
from sqlalchemy import create_engine, select, update
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import review_service
from app.db import SessionLocal, set_org_context
from app.learning_models import LlmCall
from app.llm import pricing
from app.llm.client import (
    CallOutcome,
    OpenRouterBackend,
    ProviderUnavailable,
    call_chat,
    record_local_call,
    record_to_database,
)
from app.llm.provider import ExtractionContext, MockInvoiceProvider, OpenRouterInvoiceProvider
from app.models import Base, Membership, Organization, User
from app.workflow_config import default_invoice_config
from tests.conftest import TenantFactory, postgres
from tests.test_review import make_document

CONFIG = default_invoice_config()
ORG = uuid.uuid4()
DOCUMENT = uuid.uuid4()
PAGE = (
    "Invoice\nVendor: Harbor Supply Co\nInvoice Number: HS-1\nInvoice Date: 2026-03-05\n"
    "Total: $110.00\n"
)


def openrouter(handler: Any) -> OpenRouterBackend:
    return OpenRouterBackend("test-only-key", httpx.Client(transport=httpx.MockTransport(handler)))


def completion(content: object, usage: dict[str, int] | None = None) -> httpx.Response:
    body: dict[str, Any] = {"choices": [{"message": {"content": content}}]}
    if usage is not None:
        body["usage"] = usage
    return httpx.Response(200, json=body)


@pytest.fixture(autouse=True)
def fresh_prices() -> None:
    pricing.reset_for_tests()


def test_successful_call_records_tokens_and_cost_from_the_price_table() -> None:
    rows: list[CallOutcome] = []
    result = call_chat(
        "extraction",
        [{"role": "user", "content": "hi"}],
        None,
        "openai/gpt-4o-mini",
        ORG,
        DOCUMENT,
        "trace-1",
        backend=openrouter(
            lambda request: completion(
                json.dumps({"fields": []}), {"prompt_tokens": 1_000_000, "completion_tokens": 500}
            )
        ),
        prompt_version="extraction-v3",
        recorder=rows.append,
    )
    assert result.decoded == {"fields": []}
    assert result.tokens_in == 1_000_000 and result.tokens_out == 500
    # 1M input tokens at 15 cents per 1M plus 500 output tokens at 60 cents per 1M.
    assert result.cost_cents == Decimal("15.0300")
    assert len(rows) == 1
    row = rows[0]
    assert (row.purpose, row.provider, row.model, row.ok, row.error) == (
        "extraction",
        "openrouter",
        "openai/gpt-4o-mini",
        True,
        None,
    )
    assert (row.org_id, row.document_id, row.trace_id) == (ORG, DOCUMENT, "trace-1")
    assert row.prompt_version == "extraction-v3" and row.cost_cents == Decimal("15.0300")
    assert row.latency_ms >= 0 and row.created_at.tzinfo is not None


def test_failed_calls_record_a_row_without_document_text_and_raise() -> None:
    rows: list[CallOutcome] = []
    for handler, expected in (
        (lambda request: httpx.Response(503, json={"error": "down"}), "HTTP 503"),
        (lambda request: completion("not json"), "JSONDecodeError"),
        (lambda request: httpx.Response(200, json={"choices": []}), "IndexError"),
    ):
        with pytest.raises(ProviderUnavailable):
            call_chat(
                "escalation",
                [{"role": "user", "content": "secret document text"}],
                None,
                "openai/gpt-4o-mini",
                ORG,
                None,
                None,
                backend=openrouter(handler),
                prompt_version="extraction-v3",
                recorder=rows.append,
            )
        row = rows[-1]
        assert row.ok is False and row.error is not None and row.error.startswith(expected)
        assert "secret" not in row.error
        assert row.cost_cents is None and row.tokens_in is None and row.purpose == "escalation"
    assert len(rows) == 3


def test_unknown_model_records_a_null_cost_and_warns_once(caplog: pytest.LogCaptureFixture) -> None:
    rows: list[CallOutcome] = []
    with caplog.at_level(logging.WARNING, logger="app.llm.pricing"):
        for _ in range(2):
            call_chat(
                "extraction",
                [],
                None,
                "vendor/unpriced-model",
                ORG,
                None,
                None,
                backend=openrouter(
                    lambda request: completion(
                        "{}", {"prompt_tokens": 10, "completion_tokens": 10}
                    )
                ),
                prompt_version="extraction-v3",
                recorder=rows.append,
            )
    assert [row.cost_cents for row in rows] == [None, None]
    assert [row.tokens_in for row in rows] == [10, 10]
    warnings = [record for record in caplog.records if "No price for model" in record.message]
    assert len(warnings) == 1
    # A known model whose usage was not reported cannot be priced either.
    assert pricing.cost_cents("openrouter", "openai/gpt-4o-mini", None, 5) is None


def test_price_table_env_override_merges_over_the_builtin_table(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.llm.pricing.get_settings",
        lambda: type(
            "S",
            (),
            {"llm_price_table_json": '{"vendor/custom": [100, 200], "openai/gpt-4o-mini": [1, 1]}'},
        )(),
    )
    pricing.reset_for_tests()
    assert pricing.price_for("vendor/custom") == (Decimal("100"), Decimal("200"))
    assert pricing.price_for("google/gemini-3.8-flash") == (Decimal("75"), Decimal("375"))
    custom = pricing.cost_cents("openrouter", "vendor/custom", 500_000, 250_000)
    assert custom == Decimal("100.0000")
    assert pricing.cost_cents("openrouter", "openai/gpt-4o-mini", 1_000_000, 0) == Decimal("1.0000")
    assert pricing.cost_cents("rules", "invoice-pattern-v2", None, None) == Decimal("0.0000")
    assert pricing.cost_cents("mock", "anything", None, None) == Decimal("0.0000")


def test_local_providers_record_zero_cost_rows_on_success_and_failure() -> None:
    rows: list[CallOutcome] = []
    provider = MockInvoiceProvider(recorder=rows.append)
    context = ExtractionContext(ORG, DOCUMENT, "trace-9")
    result = provider.extract_pages([PAGE], CONFIG, context)
    assert {field.name for field in result.fields} == {
        "vendor",
        "invoice_number",
        "invoice_date",
        "total",
    }
    assert result.cost_cents == Decimal("0.0000")
    with pytest.raises(Exception, match="No supported invoice fields"):
        provider.extract_pages(["Nothing to see here"], CONFIG, context)
    assert [(row.provider, row.ok, row.cost_cents) for row in rows] == [
        ("mock", True, Decimal("0.0000")),
        ("mock", False, Decimal("0.0000")),
    ]
    assert rows[1].error is not None and "expected lines such as Vendor" in rows[1].error
    assert all(row.trace_id == "trace-9" and row.document_id == DOCUMENT for row in rows)
    record_local_call(
        "agent", "rules", "m", "p", ORG, None, None, latency_ms=3, ok=True, recorder=rows.append
    )
    assert rows[-1].purpose == "agent" and rows[-1].latency_ms == 3


def test_openrouter_provider_records_extraction_and_escalation_purposes() -> None:
    rows: list[CallOutcome] = []
    seen_prompts: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        seen_prompts.append(payload)
        return completion(
            json.dumps(
                {
                    "fields": [
                        {
                            "name": "total",
                            "value": "$110.00",
                            "evidence": "Total: $110.00",
                            "page_number": 1,
                            "confidence": 0.9,
                        }
                    ]
                }
            ),
            {"prompt_tokens": 100, "completion_tokens": 20},
        )

    provider = OpenRouterInvoiceProvider(
        "test-only-key",
        "openai/gpt-4o-mini",
        httpx.Client(transport=httpx.MockTransport(handler)),
        recorder=rows.append,
    )
    full = provider.extract_pages([PAGE], CONFIG, ExtractionContext(ORG, DOCUMENT, "t"))
    subset = provider.extract_pages(
        [PAGE],
        CONFIG,
        ExtractionContext(ORG, DOCUMENT, "t"),
        document_type="invoice",
        field_names=["total", "invoice_date"],
    )
    assert full.cost_cents == Decimal("0.0027") and subset.cost_cents == Decimal("0.0027")
    assert [row.purpose for row in rows] == ["extraction", "escalation"]
    names = seen_prompts[1]["response_format"]["json_schema"]["schema"]["properties"]["fields"]
    assert names["items"]["properties"]["name"]["enum"] == ["invoice_date", "total"]
    assert "- total: Total (money, required)" in seen_prompts[1]["messages"][0]["content"]
    assert "- vendor:" not in seen_prompts[1]["messages"][0]["content"]
    assert "- vendor:" in seen_prompts[0]["messages"][0]["content"]


def test_timeline_lists_model_calls_before_the_extraction_run() -> None:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    org_id, user_id = uuid.uuid4(), uuid.uuid4()
    now = datetime.now(UTC).replace(microsecond=0)
    with Session(engine) as session:
        session.add(Organization(id=org_id, slug="ledger", name="Ledger"))
        session.add(User(id=user_id, email="ledger@example.com", password_hash="unused"))
        session.flush()
        session.add(Membership(org_id=org_id, user_id=user_id, role="admin", status="active"))
        document = make_document(org_id, user_id, "a.pdf", "needs_review", now)
        session.add(document)
        session.flush()
        for index, ok in enumerate((False, True)):
            session.add(
                LlmCall(
                    org_id=org_id,
                    document_id=document.id,
                    purpose="extraction",
                    provider="openrouter",
                    model="openai/gpt-4o-mini",
                    prompt_version="extraction-v3",
                    tokens_in=120 if ok else None,
                    tokens_out=30 if ok else None,
                    cost_cents=Decimal("0.0036") if ok else None,
                    latency_ms=800 + index,
                    ok=ok,
                    error=None if ok else "HTTP 502",
                    trace_id="trace-x",
                    created_at=now.replace(second=index),
                )
            )
        session.commit()
        entries = review_service.timeline(session, org_id, document.id)
    assert [(entry.kind, entry.event_type) for entry in entries] == [
        ("llm", "llm.call"),
        ("llm", "llm.call"),
    ]
    assert entries[0].summary == (
        "Model call (extraction) with openrouter openai/gpt-4o-mini failed: HTTP 502"
    )
    assert entries[1].detail == {
        "purpose": "extraction",
        "provider": "openrouter",
        "model": "openai/gpt-4o-mini",
        "prompt_version": "extraction-v3",
        "tokens_in": 120,
        "tokens_out": 30,
        "cost_cents": 0.0036,
        "latency_ms": 801,
        "ok": True,
        "error": None,
        "trace_id": "trace-x",
    }


@postgres
def test_ledger_rows_are_tenant_isolated_and_append_only(make_tenant: TenantFactory) -> None:
    tenant, other = make_tenant(), make_tenant()
    outcome = CallOutcome(
        purpose="extraction",
        provider="rules",
        model="invoice-pattern-v2",
        prompt_version="rules-v2",
        org_id=tenant.org_id,
        document_id=None,
        trace_id="t",
        tokens_in=None,
        tokens_out=None,
        cost_cents=Decimal("0.0000"),
        latency_ms=1,
        ok=True,
        error=None,
        created_at=datetime.now(UTC),
    )
    record_to_database(outcome)
    # Outside any tenant context nothing is written, and the call does not fail.
    record_to_database(outcome.__class__(**{**outcome.__dict__, "org_id": None}))
    with SessionLocal() as session:
        set_org_context(session, tenant.org_id)
        rows = session.scalars(select(LlmCall)).all()
        assert [(row.provider, row.ok, row.cost_cents) for row in rows] == [
            ("rules", True, Decimal("0.0000"))
        ]
        with pytest.raises(ProgrammingError), session.begin_nested():
            session.execute(update(LlmCall).where(LlmCall.id == rows[0].id).values(ok=False))
    with SessionLocal() as session:
        set_org_context(session, other.org_id)
        assert session.scalars(select(LlmCall)).all() == []
