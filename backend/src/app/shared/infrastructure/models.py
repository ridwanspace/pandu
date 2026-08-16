"""Shared-kernel ORM models. One table: llm_calls, the append-only cost ledger
every metered vendor call writes to (see ai/metering.py and ai/cost_store.py)."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Index, Numeric, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.infrastructure.db.base import Base


class LlmCallModel(Base):
    __tablename__ = "llm_calls"
    __table_args__ = (Index("ix_llm_calls_created_at", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    operation: Mapped[str] = mapped_column(String(16), nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(nullable=False, default=0)
    completion_tokens: Mapped[int] = mapped_column(nullable=False, default=0)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)
    latency_ms: Mapped[int] = mapped_column(nullable=False)
    fallback_used: Mapped[bool] = mapped_column(nullable=False, default=False)
    trace_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
