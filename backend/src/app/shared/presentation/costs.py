"""GET /stats/costs — the cost dashboard endpoint (BRIEF contract).

The reader is declared as a structural Protocol over plain tuples so this
module never imports the infrastructure implementation (layer siblings stay
independent); bootstrap overrides ``get_cost_stats_reader`` with
``app.shared.infrastructure.ai.cost_store.CostStatsReader``.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Annotated, Protocol

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.shared.presentation.auth import require_api_key

if TYPE_CHECKING:
    from collections.abc import Sequence


class CostStatsReaderPort(Protocol):
    """Structural port for cost aggregates.

    ``by_model`` rows: (model, operation, calls, prompt_tokens,
    completion_tokens, cost_usd); ``daily`` rows: (day, cost_usd, calls).
    """

    async def total_usd(self, days: int) -> Decimal: ...

    async def by_model(self, days: int) -> Sequence[tuple[str, str, int, int, int, Decimal]]: ...

    async def daily(self, days: int) -> Sequence[tuple[date, Decimal, int]]: ...


def get_cost_stats_reader() -> CostStatsReaderPort:
    """Placeholder dependency; bootstrap must override it with a wired reader."""
    msg = "cost stats reader is not wired; override get_cost_stats_reader in bootstrap"
    raise RuntimeError(msg)


class ModelCostOut(BaseModel):
    model: str
    operation: str
    calls: int
    prompt_tokens: int
    completion_tokens: int
    cost_usd: str


class DailyCostOut(BaseModel):
    date: date
    cost_usd: str
    calls: int


class CostStatsOut(BaseModel):
    total_usd: str
    by_model: list[ModelCostOut]
    daily: list[DailyCostOut]


router = APIRouter(prefix="/stats", tags=["stats"], dependencies=[Depends(require_api_key)])

_MICRO_USD = Decimal("0.000001")


def _money(value: Decimal) -> str:
    """Fixed-point string, 6 decimals — matches the Numeric(12, 6) ledger and
    avoids scientific notation in JSON."""
    return format(value.quantize(_MICRO_USD), "f")


@router.get("/costs", response_model=CostStatsOut)
async def get_cost_stats(
    reader: Annotated[CostStatsReaderPort, Depends(get_cost_stats_reader)],
    days: Annotated[int, Query(ge=1, le=365)] = 30,
) -> CostStatsOut:
    total = await reader.total_usd(days)
    by_model = await reader.by_model(days)
    daily = await reader.daily(days)
    return CostStatsOut(
        total_usd=_money(total),
        by_model=[
            ModelCostOut(
                model=model,
                operation=operation,
                calls=calls,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                cost_usd=_money(cost_usd),
            )
            for model, operation, calls, prompt_tokens, completion_tokens, cost_usd in by_model
        ],
        daily=[
            DailyCostOut(date=day, cost_usd=_money(cost_usd), calls=calls)
            for day, cost_usd, calls in daily
        ],
    )
