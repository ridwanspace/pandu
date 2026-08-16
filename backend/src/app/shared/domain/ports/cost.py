"""Cost-metering port: every vendor call emits one CostEvent (tokens x price
table -> USD), persisted for the dashboard. Counts only — never prompt text."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal, Protocol

from app.shared.domain.values import ModelRef, TokenUsage

Operation = Literal["chat", "embedding", "rerank", "judge"]


@dataclass(frozen=True, slots=True)
class CostEvent:
    model: ModelRef
    operation: Operation
    usage: TokenUsage
    cost_usd: Decimal
    latency_ms: int
    fallback_used: bool = False
    trace_id: str | None = None


class CostRecorder(Protocol):
    async def record(self, event: CostEvent) -> None: ...
