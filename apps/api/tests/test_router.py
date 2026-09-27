"""The two-tier router: escalation of failing fields only, and the agreement signal."""

import uuid
from collections.abc import Sequence
from decimal import Decimal

from app.llm.client import CallOutcome, ProviderUnavailable
from app.llm.provider import (
    ExtractionContext,
    ExtractionResult,
    FewShotExample,
    RulesInvoiceProvider,
)
from app.llm.router import DISAGREEMENT_REASON, ModelRouter, failing_fields, merge_fields
from app.workflow_config import WorkflowConfigModel, default_invoice_config

CONFIG = default_invoice_config()
ORG = uuid.uuid4()
PAGE = (
    "Invoice\nVendor: Harbor Supply Co\nInvoice Number: HS-1001\nInvoice Date: 05-Mar-26\n"
    "Subtotal: $100.00\nTax: $10.00\nTotal: $120.00\nAmount due: $110.00\nCurrency: USD\n"
)
CLEAN_PAGE = PAGE.replace("Total: $120.00", "Total: $110.00")


class Tier2Double(RulesInvoiceProvider):
    """A deterministic 'stronger model' that may answer differently for some fields."""

    name = "rules"
    model = "tier2-double"
    paid = False

    def __init__(
        self,
        overrides: dict[str, tuple[str, str] | None],
        recorder: Sequence[CallOutcome] | None = None,
        fail: bool = False,
    ) -> None:
        super().__init__(recorder=lambda outcome: None)
        self.overrides = overrides
        self.requests: list[Sequence[str] | None] = []
        self.fail = fail

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
        self.requests.append(field_names)
        if self.fail:
            raise ProviderUnavailable("tier 2 is down")
        result = super().extract_pages(
            pages, config, context, document_type=document_type, field_names=field_names
        )
        fields = []
        for value in result.fields:
            if value.name in self.overrides:
                replacement = self.overrides[value.name]
                if replacement is None:
                    continue
                new_value, evidence = replacement
                fields.append(value.__class__(value.name, new_value, evidence, 1, 0.95))
            else:
                fields.append(value)
        return ExtractionResult(
            fields=fields,
            pages=pages,
            document_type=result.document_type,
            model=self.model,
            prompt_version="rules-v2",
            tokens_in=None,
            tokens_out=None,
            latency_ms=1,
            cost_cents=Decimal("0.5000"),
        )


def tier1(rows: list[CallOutcome] | None = None) -> RulesInvoiceProvider:
    return RulesInvoiceProvider(recorder=(rows.append if rows is not None else lambda o: None))


def test_no_failing_fields_means_no_escalation_and_agreement_stays_none() -> None:
    tier2 = Tier2Double({})
    assessment = ModelRouter(tier1(), tier2).run([CLEAN_PAGE], CONFIG)
    assert assessment.escalated is False and assessment.tier2_model is None
    assert tier2.requests == []
    assert all(item.signals["model_agreement"] is None for item in assessment.evaluation.fields)
    assert assessment.cost_cents == Decimal("0.0000") and assessment.provider_name == "rules"


def test_only_failing_fields_are_escalated_and_agreement_is_scored_per_field() -> None:
    rows: list[CallOutcome] = []
    # Tier 2 confirms the subtotal (agreement 1.0), corrects the total (agreement 0.0)
    # and finds no tax at all (kept from tier 1, agreement 0.0).
    tier2 = Tier2Double({"total": ("$110.00", "Amount due: $110.00"), "tax": None})
    context = ExtractionContext(ORG, uuid.uuid4(), "trace")
    assessment = ModelRouter(tier1(rows), tier2).run([PAGE], CONFIG, context)
    # The failed totals rule names subtotal, tax and total; nothing else fails.
    assert tier2.requests == [["subtotal", "tax", "total"]]
    assert assessment.escalated is True and assessment.tier2_model == "tier2-double"
    assert assessment.escalated_fields == ["subtotal", "tax", "total"]
    assert assessment.agreement == {"subtotal": 1.0, "tax": 0.0, "total": 0.0}
    by_name = {item.name: item for item in assessment.evaluation.fields}
    assert by_name["total"].value == "$110.00" and by_name["tax"].value == "$10.00"
    assert by_name["subtotal"].signals["model_agreement"] == 1.0
    assert by_name["total"].signals["model_agreement"] == 0.0
    assert by_name["vendor"].signals["model_agreement"] is None
    assert DISAGREEMENT_REASON in by_name["total"].reasons
    assert DISAGREEMENT_REASON in by_name["tax"].reasons
    assert DISAGREEMENT_REASON not in by_name["subtotal"].reasons
    # With the corrected total the rule passes again; the disagreement still costs confidence.
    assert assessment.evaluation.rule_results[0].passed is True
    assert by_name["total"].signals["cross_field"] == 1.0
    assert by_name["total"].confidence == round(
        (0.35 + 0.25 + 0.20 + 0.05 * 0.95) / (0.35 + 0.25 + 0.20 + 0.10 + 0.05), 4
    )
    assert assessment.cost_cents == Decimal("0.5000")
    assert assessment.result.model == "invoice-pattern-v2"
    assert [value.name for value in assessment.result.fields] == [
        "vendor",
        "invoice_number",
        "invoice_date",
        "subtotal",
        "tax",
        "total",
        "currency",
    ]
    assert [row.purpose for row in rows] == ["extraction"]


def test_agreement_normalizes_whitespace_and_case() -> None:
    merged, agreement = merge_fields(
        RulesInvoiceProvider(recorder=lambda o: None).extract_pages([PAGE], CONFIG).fields,
        Tier2Double(
            {
                "total": ("$120.00 ", "Total: $120.00"),
                "subtotal": ("$100.00", "Subtotal: $100.00"),
            }
        )
        .extract_pages([PAGE], CONFIG, field_names=["subtotal", "total"])
        .fields,
        ["subtotal", "total"],
    )
    assert agreement == {"subtotal": 1.0, "total": 1.0}
    assert [value.name for value in merged][-2:] == ["total", "currency"]


def test_missing_required_field_is_escalated_and_recovered_from_tier_two() -> None:
    page = CLEAN_PAGE.replace("Total: $110.00\n", "Amount Due: $110.00\n")
    tier2 = Tier2Double({})

    class Finder(Tier2Double):
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
            self.requests.append(field_names)
            value = RulesInvoiceProvider(recorder=lambda o: None).extract_pages(
                [pages[0] + "Total: $110.00\n"], config, field_names=["total"]
            )
            return ExtractionResult(
                fields=value.fields, pages=pages, document_type="invoice", model=self.model,
                prompt_version="rules-v2", tokens_in=None, tokens_out=None, latency_ms=1,
            )

    tier2 = Finder({})
    assessment = ModelRouter(tier1(), tier2).run([page], CONFIG)
    # "total" was missing (required) and the totals rule could not be evaluated.
    assert tier2.requests == [["total"]]
    by_name = {item.name: item for item in assessment.evaluation.fields}
    assert by_name["total"].value == "$110.00"
    assert assessment.agreement == {"total": 0.0}
    assert DISAGREEMENT_REASON in by_name["total"].reasons


def test_tier_two_outage_keeps_the_tier_one_answer() -> None:
    tier2 = Tier2Double({}, fail=True)
    assessment = ModelRouter(tier1(), tier2).run([PAGE], CONFIG)
    assert assessment.escalated is False and assessment.tier2_model == "tier2-double"
    flagged = {item.name for item in assessment.evaluation.fields if item.status == "needs_review"}
    assert flagged == {"subtotal", "tax", "total"}
    assert assessment.agreement == {}


def test_budget_check_blocks_paid_escalation_only() -> None:
    class PaidDouble(Tier2Double):
        paid = True

    calls: list[uuid.UUID] = []
    tier2 = PaidDouble({"total": ("$110.00", "Amount due: $110.00")})
    context = ExtractionContext(ORG, None, None)

    def refuse(org_id: uuid.UUID) -> bool:
        calls.append(org_id)
        return False

    blocked = ModelRouter(tier1(), tier2, allow_paid_call=refuse).run([PAGE], CONFIG, context)
    assert blocked.escalated is False and tier2.requests == [] and calls == [ORG]
    allowed = ModelRouter(tier1(), tier2, allow_paid_call=lambda org: True).run(
        [PAGE], CONFIG, context
    )
    assert allowed.escalated is True
    # A free tier-2 provider never consults the budget.
    free = Tier2Double({"total": ("$110.00", "Amount due: $110.00")})
    ModelRouter(tier1(), free, allow_paid_call=refuse).run([PAGE], CONFIG, context)
    assert free.requests == [["subtotal", "tax", "total"]] and calls == [ORG]


def test_failing_fields_are_deduplicated_and_ordered() -> None:
    provider = tier1()
    result = provider.extract_pages([PAGE], CONFIG)
    from app.confidence import evaluate

    evaluation = evaluate(result.fields, [PAGE], CONFIG.document_types[0])
    assert failing_fields(evaluation, CONFIG.document_types[0]) == ["subtotal", "tax", "total"]
