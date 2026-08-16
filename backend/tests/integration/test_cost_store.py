"""Cost ledger adapters: PostgresCostRecorder inserts and the CostStatsReader
aggregations (windowed totals, per-model/operation grouping, daily buckets).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from app.shared.domain.ports.cost import CostEvent, Operation
from app.shared.domain.values import ModelRef, TokenUsage
from app.shared.infrastructure.ai.cost_store import CostStatsReader, PostgresCostRecorder
from app.shared.infrastructure.models import LlmCallModel
from tests.integration.support import SessionFactory

_CHAT_MODEL = ModelRef(provider="openai", name="gpt-4o-mini")
_EMBED_MODEL = ModelRef(provider="openai", name="text-embedding-3-small")


def _event(
    *,
    model: ModelRef = _CHAT_MODEL,
    operation: Operation = "chat",
    prompt: int = 100,
    completion: int = 20,
    cost: str = "0.000450",
) -> CostEvent:
    return CostEvent(
        model=model,
        operation=operation,
        usage=TokenUsage(prompt_tokens=prompt, completion_tokens=completion),
        cost_usd=Decimal(cost),
        latency_ms=120,
    )


async def _insert_row(
    session_factory: SessionFactory,
    *,
    created_at: datetime,
    cost: str,
    operation: str = "chat",
) -> None:
    """Seed a ledger row at an arbitrary time (the recorder always stamps now)."""
    async with session_factory() as session, session.begin():
        session.add(
            LlmCallModel(
                id=uuid4(),
                created_at=created_at,
                provider=_CHAT_MODEL.provider,
                model=_CHAT_MODEL.name,
                operation=operation,
                prompt_tokens=10,
                completion_tokens=5,
                cost_usd=Decimal(cost),
                latency_ms=80,
                fallback_used=False,
            )
        )


async def test_record_persists_one_row_per_event(
    session_factory: SessionFactory,
) -> None:
    recorder = PostgresCostRecorder(session_factory)
    reader = CostStatsReader(session_factory)

    await recorder.record(_event(cost="0.000450"))
    await recorder.record(
        _event(model=_EMBED_MODEL, operation="embedding", prompt=900, completion=0, cost="0.000018")
    )

    total = await reader.total_usd(30)
    assert total == Decimal("0.000468")

    rows = await reader.by_model(30)
    assert {(r.model, r.operation) for r in rows} == {
        ("openai/gpt-4o-mini", "chat"),
        ("openai/text-embedding-3-small", "embedding"),
    }


async def test_by_model_aggregates_and_orders_by_cost(
    session_factory: SessionFactory,
) -> None:
    recorder = PostgresCostRecorder(session_factory)
    reader = CostStatsReader(session_factory)
    await recorder.record(_event(prompt=100, completion=20, cost="0.000450"))
    await recorder.record(_event(prompt=300, completion=60, cost="0.001350"))
    await recorder.record(
        _event(model=_EMBED_MODEL, operation="embedding", prompt=900, completion=0, cost="0.000018")
    )

    rows = await reader.by_model(30)

    assert [r.cost_usd for r in rows] == sorted((r.cost_usd for r in rows), reverse=True)
    chat_row = next(r for r in rows if r.operation == "chat")
    assert chat_row.model == "openai/gpt-4o-mini"
    assert chat_row.calls == 2
    assert chat_row.prompt_tokens == 400
    assert chat_row.completion_tokens == 80
    assert chat_row.cost_usd == Decimal("0.001800")
    embed_row = next(r for r in rows if r.operation == "embedding")
    assert embed_row.calls == 1
    assert embed_row.cost_usd == Decimal("0.000018")


async def test_window_excludes_events_older_than_requested_days(
    session_factory: SessionFactory,
) -> None:
    recorder = PostgresCostRecorder(session_factory)
    reader = CostStatsReader(session_factory)
    await recorder.record(_event(cost="0.000450"))
    await _insert_row(
        session_factory,
        created_at=datetime.now(UTC) - timedelta(days=40),
        cost="9.999999",
    )

    assert await reader.total_usd(30) == Decimal("0.000450")
    assert await reader.total_usd(60) == Decimal("10.000449")
    assert len(await reader.daily(30)) == 1


async def test_daily_buckets_are_ascending_per_day(
    session_factory: SessionFactory,
) -> None:
    reader = CostStatsReader(session_factory)
    now = datetime.now(UTC)
    yesterday = now - timedelta(days=1)
    await _insert_row(session_factory, created_at=yesterday, cost="0.000100")
    await _insert_row(session_factory, created_at=yesterday, cost="0.000200")
    await _insert_row(session_factory, created_at=now, cost="0.000300")

    daily = await reader.daily(30)

    assert [row.day for row in daily] == [yesterday.date(), now.date()]
    assert daily[0].cost_usd == Decimal("0.000300")
    assert daily[0].calls == 2
    assert daily[1].cost_usd == Decimal("0.000300")
    assert daily[1].calls == 1


async def test_empty_ledger_totals_zero(session_factory: SessionFactory) -> None:
    reader = CostStatsReader(session_factory)
    assert await reader.total_usd(30) == Decimal("0")
    assert await reader.by_model(30) == []
    assert await reader.daily(30) == []


async def test_recorder_preserves_decimal_precision(
    session_factory: SessionFactory,
) -> None:
    recorder = PostgresCostRecorder(session_factory)
    reader = CostStatsReader(session_factory)
    await recorder.record(_event(cost="0.001234"))

    total = await reader.total_usd(30)

    assert total == Decimal("0.001234")
    assert total == pytest.approx(Decimal("0.001234"))
