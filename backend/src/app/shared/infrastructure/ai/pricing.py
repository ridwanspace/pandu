"""Static price table: tokens x USD-per-million -> Decimal cost.

Prices are a snapshot (2026-08, public list prices) — good enough for the cost
dashboard; exactness is not the goal, comparability is. Unknown models cost
Decimal("0") and warn once per model so a new deployment is visible in logs
without spamming them.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from collections.abc import Sequence

    from app.shared.domain.values import ModelRef, TokenUsage

_log = structlog.get_logger(__name__)

_ONE_MILLION = Decimal(1_000_000)
_CENT_MICRO = Decimal("0.000001")  # matches the llm_calls Numeric(12, 6) column


@dataclass(frozen=True, slots=True)
class PriceRow:
    """One pricing rule; ``model_prefix`` matches the vendor model name by
    longest prefix, so ``gpt-4.1-mini`` beats ``gpt-4.1`` for gpt-4.1-mini."""

    provider: str
    model_prefix: str
    usd_per_1m_prompt: Decimal
    usd_per_1m_completion: Decimal


DEFAULT_PRICE_ROWS: tuple[PriceRow, ...] = (
    # OpenAI chat
    PriceRow("openai", "gpt-4o-mini", Decimal("0.15"), Decimal("0.60")),
    PriceRow("openai", "gpt-4o", Decimal("2.50"), Decimal("10.00")),
    PriceRow("openai", "gpt-4.1-nano", Decimal("0.10"), Decimal("0.40")),
    PriceRow("openai", "gpt-4.1-mini", Decimal("0.40"), Decimal("1.60")),
    PriceRow("openai", "gpt-4.1", Decimal("2.00"), Decimal("8.00")),
    PriceRow("openai", "o1", Decimal("15.00"), Decimal("60.00")),
    PriceRow("openai", "o3-mini", Decimal("1.10"), Decimal("4.40")),
    PriceRow("openai", "o3", Decimal("2.00"), Decimal("8.00")),
    PriceRow("openai", "o4-mini", Decimal("1.10"), Decimal("4.40")),
    # OpenAI embeddings (input-only pricing)
    PriceRow("openai", "text-embedding-3-small", Decimal("0.02"), Decimal("0")),
    PriceRow("openai", "text-embedding-3-large", Decimal("0.13"), Decimal("0")),
    # Gemini
    PriceRow("gemini", "gemini-2.0-flash-lite", Decimal("0.075"), Decimal("0.30")),
    PriceRow("gemini", "gemini-2.0-flash", Decimal("0.10"), Decimal("0.40")),
    PriceRow("gemini", "gemini-2.5-flash-lite", Decimal("0.10"), Decimal("0.40")),
    PriceRow("gemini", "gemini-2.5-flash", Decimal("0.30"), Decimal("2.50")),
    PriceRow("gemini", "gemini-2.5-pro", Decimal("1.25"), Decimal("10.00")),
    PriceRow("gemini", "gemini-embedding", Decimal("0.15"), Decimal("0")),
    # DeepSeek
    PriceRow("deepseek", "deepseek-chat", Decimal("0.27"), Decimal("1.10")),
    PriceRow("deepseek", "deepseek-reasoner", Decimal("0.55"), Decimal("2.19")),
)


class PriceTable:
    def __init__(self, rows: Sequence[PriceRow] | None = None) -> None:
        self._rows: tuple[PriceRow, ...] = tuple(rows) if rows is not None else DEFAULT_PRICE_ROWS
        self._warned_models: set[str] = set()

    def find(self, model: ModelRef) -> PriceRow | None:
        """Longest-prefix match within the model's provider."""
        best: PriceRow | None = None
        for row in self._rows:
            if row.provider != model.provider or not model.name.startswith(row.model_prefix):
                continue
            if best is None or len(row.model_prefix) > len(best.model_prefix):
                best = row
        return best

    def cost_for(self, model: ModelRef, usage: TokenUsage) -> Decimal:
        row = self.find(model)
        if row is None:
            key = str(model)
            if key not in self._warned_models:
                self._warned_models.add(key)
                _log.warning(
                    "no price for model; cost recorded as 0",
                    provider=model.provider,
                    model=model.name,
                )
            return Decimal("0")
        cost = (
            Decimal(usage.prompt_tokens) * row.usd_per_1m_prompt
            + Decimal(usage.completion_tokens) * row.usd_per_1m_completion
        ) / _ONE_MILLION
        return cost.quantize(_CENT_MICRO, rounding=ROUND_HALF_UP)
