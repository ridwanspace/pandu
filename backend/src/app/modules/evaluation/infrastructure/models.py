"""ORM model for eval runs. Metrics and config are JSONB — eval metric sets
evolve (retrieval-only vs judge vs ragas) and a sparse wide table would churn
migrations for no query benefit; runs are only ever listed, newest first."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, Index, String
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.infrastructure.db.base import Base


class EvalRunModel(Base):
    __tablename__ = "eval_runs"
    __table_args__ = (Index("ix_eval_runs_created_at", "created_at"),)

    id: Mapped[UUID] = mapped_column(postgresql.UUID(as_uuid=True), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    dataset_version: Mapped[str] = mapped_column(String(120), nullable=False)
    config: Mapped[dict[str, str]] = mapped_column(postgresql.JSONB, nullable=False, default=dict)
    metrics: Mapped[dict[str, float]] = mapped_column(
        postgresql.JSONB, nullable=False, default=dict
    )
