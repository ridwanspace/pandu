"""Persistence port for eval runs. Postgres implements it in infrastructure;
unit tests use an in-memory fake."""

from __future__ import annotations

from typing import Protocol

from app.modules.evaluation.domain.entities import EvalRun


class EvalRunRepository(Protocol):
    async def add(self, run: EvalRun) -> None: ...

    async def list_recent(self, limit: int) -> list[EvalRun]:
        """Most recent first."""
        ...
