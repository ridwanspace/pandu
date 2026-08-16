"""PostgresEvalRunRepository: add + list_recent ordering, limit, JSONB fidelity."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.modules.evaluation.domain.entities import EvalRun
from app.modules.evaluation.infrastructure.repositories import PostgresEvalRunRepository
from tests.integration.support import SessionFactory


def _run(*, minutes_ago: int, recall: float) -> EvalRun:
    return EvalRun(
        id=uuid4(),
        created_at=datetime.now(UTC) - timedelta(minutes=minutes_ago),
        dataset_version="golden_v1",
        config={"reranker": "none", "rrf_k": "60"},
        metrics={"recall_at_k": recall, "mrr": 0.5},
    )


async def test_add_and_roundtrip(session_factory: SessionFactory) -> None:
    repo = PostgresEvalRunRepository(session_factory)
    run = _run(minutes_ago=0, recall=0.8)

    await repo.add(run)
    loaded = await repo.list_recent(10)

    assert len(loaded) == 1
    got = loaded[0]
    assert got.id == run.id
    assert got.created_at == run.created_at
    assert got.dataset_version == "golden_v1"
    assert got.config == {"reranker": "none", "rrf_k": "60"}
    assert got.metrics == {"recall_at_k": 0.8, "mrr": 0.5}
    assert isinstance(got.metrics["recall_at_k"], float)


async def test_list_recent_orders_newest_first_and_limits(
    session_factory: SessionFactory,
) -> None:
    repo = PostgresEvalRunRepository(session_factory)
    oldest = _run(minutes_ago=30, recall=0.1)
    middle = _run(minutes_ago=20, recall=0.2)
    newest = _run(minutes_ago=10, recall=0.3)
    for run in (middle, oldest, newest):  # insertion order must not matter
        await repo.add(run)

    top_two = await repo.list_recent(2)

    assert [r.id for r in top_two] == [newest.id, middle.id]
    assert len(await repo.list_recent(50)) == 3
