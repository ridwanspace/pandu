"""Postgres-backed cost recording and aggregation over the llm_calls ledger.

The recorder runs its own short transaction per event: cost accounting must
not ride on (or roll back with) the caller's business transaction. The stats
reader feeds GET /stats/costs; it returns plain tuples so the presentation
layer can depend on a structural Protocol instead of importing this module
(layer siblings stay independent — wiring happens in bootstrap).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, NamedTuple
from uuid import uuid4

from sqlalchemy import Date, cast, func, select

from app.shared.infrastructure.models import LlmCallModel

if TYPE_CHECKING:
    from datetime import date

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from app.shared.domain.ports.cost import CostEvent

_ZERO_USD = Decimal("0")


class PostgresCostRecorder:
    """CostRecorder adapter: one INSERT per CostEvent."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def record(self, event: CostEvent) -> None:
        async with self._session_factory() as session, session.begin():
            session.add(
                LlmCallModel(
                    id=uuid4(),
                    created_at=datetime.now(UTC),
                    provider=event.model.provider,
                    model=event.model.name,
                    operation=event.operation,
                    prompt_tokens=event.usage.prompt_tokens,
                    completion_tokens=event.usage.completion_tokens,
                    cost_usd=event.cost_usd,
                    latency_ms=event.latency_ms,
                    fallback_used=event.fallback_used,
                    trace_id=event.trace_id,
                )
            )


class ModelUsageRow(NamedTuple):
    """Aggregate per (model, operation); ``model`` is ``provider/name``."""

    model: str
    operation: str
    calls: int
    prompt_tokens: int
    completion_tokens: int
    cost_usd: Decimal


class DailyUsageRow(NamedTuple):
    day: date
    cost_usd: Decimal
    calls: int


def _cutoff(days: int) -> datetime:
    return datetime.now(UTC) - timedelta(days=days)


class CostStatsReader:
    """Read-side aggregates for the cost dashboard (satisfies the structural
    port declared in ``app.shared.presentation.costs``)."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def total_usd(self, days: int) -> Decimal:
        stmt = select(func.coalesce(func.sum(LlmCallModel.cost_usd), _ZERO_USD)).where(
            LlmCallModel.created_at >= _cutoff(days)
        )
        async with self._session_factory() as session:
            result = await session.execute(stmt)
            return Decimal(result.scalar_one())

    async def by_model(self, days: int) -> list[ModelUsageRow]:
        cost_sum = func.coalesce(func.sum(LlmCallModel.cost_usd), _ZERO_USD)
        stmt = (
            select(
                LlmCallModel.provider,
                LlmCallModel.model,
                LlmCallModel.operation,
                func.count(LlmCallModel.id),
                func.coalesce(func.sum(LlmCallModel.prompt_tokens), 0),
                func.coalesce(func.sum(LlmCallModel.completion_tokens), 0),
                cost_sum,
            )
            .where(LlmCallModel.created_at >= _cutoff(days))
            .group_by(LlmCallModel.provider, LlmCallModel.model, LlmCallModel.operation)
            .order_by(cost_sum.desc())
        )
        async with self._session_factory() as session:
            result = await session.execute(stmt)
            rows: list[ModelUsageRow] = []
            for provider, model, operation, calls, prompt, completion, cost in result.all():
                rows.append(
                    ModelUsageRow(
                        model=f"{provider}/{model}",
                        operation=str(operation),
                        calls=int(calls),
                        prompt_tokens=int(prompt),
                        completion_tokens=int(completion),
                        cost_usd=Decimal(cost),
                    )
                )
            return rows

    async def daily(self, days: int) -> list[DailyUsageRow]:
        day_column = cast(func.date_trunc("day", LlmCallModel.created_at), Date)
        stmt = (
            select(
                day_column,
                func.coalesce(func.sum(LlmCallModel.cost_usd), _ZERO_USD),
                func.count(LlmCallModel.id),
            )
            .where(LlmCallModel.created_at >= _cutoff(days))
            .group_by(day_column)
            .order_by(day_column)
        )
        async with self._session_factory() as session:
            result = await session.execute(stmt)
            return [
                DailyUsageRow(day=day, cost_usd=Decimal(cost_usd), calls=int(calls))
                for day, cost_usd, calls in result.all()
            ]
