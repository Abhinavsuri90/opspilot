"""Two-tier model router: a cheap first pass, a stronger second pass for what it missed.

Tier 1 extracts every configured field. When a field scores below its threshold, a
required field is missing, or a cross-field rule fails, tier 2 is asked for exactly those
fields with the schema's name enum restricted to them. The ``model_agreement`` signal
compares the two answers per field: 1.0 when they match after whitespace and case
normalization, 0.0 when they differ (the tier-2 value is kept and the field carries the
reason "Models disagreed"), and ``None`` for fields that were never escalated. Design
notes: docs/adr/009-learning-loop-and-router.md.
"""

from __future__ import annotations

import logging
import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal

from app import rules
from app.confidence import Evaluation, evaluate
from app.llm.provider import (
    ExtractedValue,
    ExtractionContext,
    ExtractionProvider,
    ExtractionResult,
    ProviderUnavailable,
)
from app.memory import EMPTY_CONTEXT, MemoryContext, priors_for
from app.workflow_config import DocumentTypeSpec, WorkflowConfigModel

logger = logging.getLogger(__name__)
DISAGREEMENT_REASON = "Models disagreed"
_WHITESPACE = re.compile(r"\s+")


@dataclass(frozen=True)
class Assessment:
    """Extraction plus scoring for one document, with the router's bookkeeping."""

    result: ExtractionResult
    type_spec: DocumentTypeSpec
    evaluation: Evaluation
    tier1_model: str
    tier2_model: str | None
    escalated: bool
    provider_name: str = ""
    escalated_fields: list[str] = field(default_factory=list)
    agreement: dict[str, float] = field(default_factory=dict)
    memory_prior: dict[str, float | None] = field(default_factory=dict)
    cost_cents: Decimal | None = Decimal("0.0000")
    vendor_key: str | None = None


def normalize_value(value: str) -> str:
    return _WHITESPACE.sub(" ", value).strip().casefold()


def failing_fields(evaluation: Evaluation, type_spec: DocumentTypeSpec) -> list[str]:
    """Fields below threshold or missing, plus every field a failed rule references."""
    names = [item.name for item in evaluation.fields if item.status == "needs_review"]
    failed = {rule.name for rule in evaluation.rule_results if rule.passed is False}
    for rule in type_spec.rules:
        if rule.name in failed:
            names.extend(sorted(rules.identifiers(rule.parsed())))
    ordered: list[str] = []
    for name in names:
        if name not in ordered and type_spec.field(name) is not None:
            ordered.append(name)
    return ordered


def _sum_cost(*costs: Decimal | None) -> Decimal | None:
    total = Decimal("0.0000")
    for cost in costs:
        if cost is None:
            return None
        total += cost
    return total


def merge_fields(
    tier1: list[ExtractedValue], tier2: list[ExtractedValue], escalated: list[str]
) -> tuple[list[ExtractedValue], dict[str, float]]:
    """Tier-2 rows replace tier-1 rows for escalated fields; agreement per escalated field."""
    first = {value.name: value for value in tier1}
    second = {value.name: value for value in tier2}
    agreement: dict[str, float] = {}
    merged: list[ExtractedValue] = [value for value in tier1 if value.name not in escalated]
    for name in escalated:
        one, two = first.get(name), second.get(name)
        if one is None and two is None:
            continue
        if two is None:
            # The stronger model found nothing it could ground: keep the evidence a reviewer
            # can see, but say the models did not agree.
            assert one is not None
            merged.append(one)
            agreement[name] = 0.0
            continue
        merged.append(two)
        same = one is not None and normalize_value(one.value) == normalize_value(two.value)
        agreement[name] = 1.0 if same else 0.0
    order = {value.name: index for index, value in enumerate(tier1)}
    merged.sort(key=lambda value: (order.get(value.name, len(order)), value.name))
    return merged, agreement


class ModelRouter:
    def __init__(
        self,
        tier1: ExtractionProvider,
        tier2: ExtractionProvider | None = None,
        *,
        allow_paid_call: Callable[[uuid.UUID], bool] | None = None,
    ) -> None:
        self.tier1 = tier1
        self.tier2 = tier2
        self.allow_paid_call = allow_paid_call

    def _may_escalate(self, context: ExtractionContext | None) -> bool:
        if self.tier2 is None:
            return False
        if (
            self.tier2.paid
            and self.allow_paid_call is not None
            and context is not None
            and context.org_id is not None
        ):
            if not self.allow_paid_call(context.org_id):
                logger.info(
                    "Escalation skipped for org %s: daily model budget reached", context.org_id
                )
                return False
        return True

    def run(
        self,
        pages: list[str],
        config: WorkflowConfigModel,
        context: ExtractionContext | None = None,
        memory: MemoryContext | None = None,
    ) -> Assessment:
        memory = memory or EMPTY_CONTEXT
        result = self.tier1.extract_pages(pages, config, context, examples=memory.examples)
        type_spec = config.document_type(result.document_type) or config.document_types[0]
        party = type_spec.party_field()
        vendor_value = next(
            (
                value.value
                for value in result.fields
                if party is not None and value.name == party.name
            ),
            None,
        )
        profile = memory.profile_for(vendor_value)
        priors = priors_for(profile, type_spec, result.fields)
        evaluation = evaluate(result.fields, pages, type_spec, memory_prior=priors)
        failing = failing_fields(evaluation, type_spec)
        if not failing or not self._may_escalate(context):
            return Assessment(
                result=result,
                type_spec=type_spec,
                evaluation=evaluation,
                tier1_model=result.model,
                tier2_model=None,
                escalated=False,
                provider_name=self.tier1.name,
                memory_prior=priors,
                cost_cents=result.cost_cents,
                vendor_key=profile.key if profile else None,
            )
        assert self.tier2 is not None
        try:
            second = self.tier2.extract_pages(
                pages,
                config,
                context,
                document_type=type_spec.name,
                field_names=failing,
                examples=memory.examples,
            )
        except ProviderUnavailable:
            # Tier 1 already produced a reviewable answer; a tier-2 outage must not lose it.
            logger.warning("Tier-2 model unavailable; keeping the tier-1 result")
            return Assessment(
                result=result,
                type_spec=type_spec,
                evaluation=evaluation,
                tier1_model=result.model,
                tier2_model=self.tier2.model,
                escalated=False,
                provider_name=self.tier1.name,
                memory_prior=priors,
                cost_cents=result.cost_cents,
                vendor_key=profile.key if profile else None,
            )
        merged, agreement = merge_fields(result.fields, second.fields, failing)
        priors = priors_for(profile, type_spec, merged)
        disagreed = {
            name: [DISAGREEMENT_REASON] for name, score in agreement.items() if score == 0.0
        }
        evaluation = evaluate(
            merged,
            pages,
            type_spec,
            model_agreement=agreement,
            memory_prior=priors,
            extra_reasons=disagreed,
        )
        combined = ExtractionResult(
            fields=merged,
            pages=pages,
            document_type=type_spec.name,
            model=result.model,
            prompt_version=result.prompt_version,
            tokens_in=_sum_tokens(result.tokens_in, second.tokens_in),
            tokens_out=_sum_tokens(result.tokens_out, second.tokens_out),
            latency_ms=result.latency_ms + second.latency_ms,
            notes=result.notes + second.notes,
            cost_cents=_sum_cost(result.cost_cents, second.cost_cents),
        )
        return Assessment(
            result=combined,
            type_spec=type_spec,
            evaluation=evaluation,
            tier1_model=result.model,
            tier2_model=second.model,
            escalated=True,
            provider_name=self.tier1.name,
            escalated_fields=failing,
            agreement=agreement,
            memory_prior=priors,
            cost_cents=combined.cost_cents,
            vendor_key=profile.key if profile else None,
        )


def _sum_tokens(first: int | None, second: int | None) -> int | None:
    if first is None and second is None:
        return None
    return (first or 0) + (second or 0)
