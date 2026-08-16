"""Streaming event union yielded by AskQuestion.

The presentation layer maps these 1:1 onto SSE events; keeping them as frozen
dataclasses lets the use case stay transport-agnostic and unit-testable.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from app.modules.chat.domain.entities import Citation
from app.shared.domain.values import ModelRef, TokenUsage

# Bootstrap passes PriceTable.cost_for; the use case never owns pricing.
CostEstimator = Callable[[ModelRef, TokenUsage], Decimal]


@dataclass(frozen=True, slots=True)
class SourcesEvent:
    """Full retrieved top-k, sent before generation starts (marker = 1..k)."""

    citations: tuple[Citation, ...]


@dataclass(frozen=True, slots=True)
class TokenEvent:
    text: str


@dataclass(frozen=True, slots=True)
class UsageEvent:
    model: str
    usage: TokenUsage
    cost_usd: Decimal
    latency_ms: int


@dataclass(frozen=True, slots=True)
class DoneEvent:
    message_id: UUID


@dataclass(frozen=True, slots=True)
class ErrorEvent:
    detail: str


ChatEvent = SourcesEvent | TokenEvent | UsageEvent | DoneEvent | ErrorEvent
