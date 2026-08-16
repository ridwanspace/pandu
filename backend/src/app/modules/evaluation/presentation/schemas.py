"""API schemas for the evals endpoints (pydantic only at the edge)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.modules.evaluation.domain.entities import EvalRun


class EvalRunOut(BaseModel):
    id: UUID
    created_at: datetime
    dataset_version: str
    metrics: dict[str, float]
    config: dict[str, str]

    @classmethod
    def from_entity(cls, run: EvalRun) -> EvalRunOut:
        return cls(
            id=run.id,
            created_at=run.created_at,
            dataset_version=run.dataset_version,
            metrics=run.metrics,
            config=run.config,
        )


class EvalRunListOut(BaseModel):
    items: list[EvalRunOut]


class RunEvalIn(BaseModel):
    """Body for POST /evals/run. ``k`` overrides the wired recall horizon."""

    k: int | None = Field(default=None, ge=1, le=50)
