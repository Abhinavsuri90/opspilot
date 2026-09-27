"""Model prices and the cost of one call.

Prices are cents per one million tokens (input, output) keyed by OpenRouter model id. The
built-in table covers a few catalogue entries; ``LLM_PRICE_TABLE_JSON`` adds or overrides
entries without a deploy, and the operator should check the catalogue before relying on
the cost figures. A model that is in neither place records a null cost and is warned
about once per process, so the ledger stays complete and the KPIs count unpriced calls.
"""

from __future__ import annotations

import json
import logging
from decimal import ROUND_HALF_UP, Decimal
from functools import lru_cache

from app.config import get_settings

logger = logging.getLogger(__name__)
ONE_MILLION = Decimal(1_000_000)
CENTS = Decimal("0.0001")
# Deterministic local providers cost nothing, which keeps per-document cost defined.
FREE_PROVIDERS = frozenset({"rules", "mock"})
BUILTIN_PRICE_TABLE: dict[str, tuple[Decimal, Decimal]] = {
    # OpenRouter catalogue snapshot, 2026-09-27. Verify before enabling a paid provider.
    "google/gemini-3.8-flash": (Decimal("75"), Decimal("375")),
    "google/gemini-2.0-flash-001": (Decimal("10"), Decimal("40")),
    "google/gemini-2.5-flash-lite": (Decimal("10"), Decimal("40")),
    "google/gemini-2.5-flash": (Decimal("30"), Decimal("250")),
    "google/gemini-2.5-pro": (Decimal("125"), Decimal("1000")),
    "openai/gpt-4o-mini": (Decimal("15"), Decimal("60")),
    "openai/gpt-4.1-nano": (Decimal("10"), Decimal("40")),
    "openai/gpt-4.1-mini": (Decimal("40"), Decimal("160")),
    "openai/gpt-4.1": (Decimal("200"), Decimal("800")),
    "openai/text-embedding-3-small": (Decimal("2"), Decimal("0")),
}
_warned_models: set[str] = set()


def _parse_override(raw: str | None) -> dict[str, tuple[Decimal, Decimal]]:
    if not raw:
        return {}
    decoded = json.loads(raw)
    table: dict[str, tuple[Decimal, Decimal]] = {}
    for model, prices in dict(decoded).items():
        input_price, output_price = prices
        table[str(model)] = (Decimal(str(input_price)), Decimal(str(output_price)))
    return table


@lru_cache
def price_table() -> dict[str, tuple[Decimal, Decimal]]:
    """The built-in table with ``LLM_PRICE_TABLE_JSON`` merged over it (validated in config)."""
    return {**BUILTIN_PRICE_TABLE, **_parse_override(get_settings().llm_price_table_json)}


def price_for(model: str) -> tuple[Decimal, Decimal] | None:
    return price_table().get(model)


def cost_cents(
    provider: str, model: str, tokens_in: int | None, tokens_out: int | None
) -> Decimal | None:
    """Cost of one call in cents, ``0`` for free providers and ``None`` when unknown."""
    if provider in FREE_PROVIDERS:
        return Decimal("0.0000")
    prices = price_for(model)
    if prices is None:
        if model not in _warned_models:
            _warned_models.add(model)
            logger.warning(
                "No price for model %s; its calls record a null cost (set LLM_PRICE_TABLE_JSON)",
                model,
            )
        return None
    if tokens_in is None or tokens_out is None:
        return None
    input_price, output_price = prices
    total = (Decimal(tokens_in) * input_price + Decimal(tokens_out) * output_price) / ONE_MILLION
    return total.quantize(CENTS, rounding=ROUND_HALF_UP)


def reset_for_tests() -> None:
    price_table.cache_clear()
    _warned_models.clear()
