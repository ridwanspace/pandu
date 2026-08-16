"""Postgres-backed EvalRunRepository."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.evaluation.domain.entities import EvalRun
from app.modules.evaluation.infrastructure.models import EvalRunModel


class PostgresEvalRunRepository:
    """Implements :class:`app.modules.evaluation.domain.repositories.EvalRunRepository`."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def add(self, run: EvalRun) -> None:
        async with self._session_factory() as session:
            session.add(
                EvalRunModel(
                    id=run.id,
                    created_at=run.created_at,
                    dataset_version=run.dataset_version,
                    config=dict(run.config),
                    metrics=dict(run.metrics),
                )
            )
            await session.commit()

    async def list_recent(self, limit: int) -> list[EvalRun]:
        async with self._session_factory() as session:
            statement = select(EvalRunModel).order_by(EvalRunModel.created_at.desc()).limit(limit)
            rows = (await session.scalars(statement)).all()
        return [
            EvalRun(
                id=row.id,
                created_at=row.created_at,
                dataset_version=row.dataset_version,
                config={str(k): str(v) for k, v in row.config.items()},
                metrics={str(k): float(v) for k, v in row.metrics.items()},
            )
            for row in rows
        ]
