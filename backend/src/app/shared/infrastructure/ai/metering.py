"""Metering decorators: same ports in, same ports out, plus one CostEvent per
vendor call (latency, tokens, USD, fallback flag). Counts only — never text.

Composition order matters: metering wraps the fallback chain (or a bare
adapter), so the event reflects the model that actually answered — results and
stream completions carry their own ModelRef.
"""

from __future__ import annotations

import time
from decimal import Decimal
from typing import TYPE_CHECKING

from app.shared.domain.ports.cost import CostEvent
from app.shared.domain.ports.llm import CompletionRequest, CompletionResult, StreamCompleted
from app.shared.domain.values import ModelRef, TokenUsage
from app.shared.infrastructure.ai.fallback import reset_fallback_used, was_fallback_used

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence

    from app.shared.domain.ports.cost import CostRecorder, Operation
    from app.shared.domain.ports.embeddings import EmbeddingBatch, EmbeddingProvider
    from app.shared.domain.ports.llm import LLMProvider, StreamEvent
    from app.shared.domain.ports.reranker import RerankCandidate, RerankedItem, Reranker
    from app.shared.infrastructure.ai.pricing import PriceTable

_ZERO_USD = Decimal("0")


def _elapsed_ms(started_at: float) -> int:
    return int((time.perf_counter() - started_at) * 1000)


class MeteredLLMProvider:
    """LLMProvider decorator. Failed calls emit no event: there is no usage to
    bill and the error path is already logged by the fallback chain."""

    def __init__(
        self,
        inner: LLMProvider,
        *,
        prices: PriceTable,
        recorder: CostRecorder,
        operation: Operation = "chat",
    ) -> None:
        self._inner = inner
        self._prices = prices
        self._recorder = recorder
        self._operation: Operation = operation

    async def complete(self, request: CompletionRequest) -> CompletionResult:
        reset_fallback_used()
        started_at = time.perf_counter()
        result = await self._inner.complete(request)
        await self._recorder.record(
            CostEvent(
                model=result.model,
                operation=self._operation,
                usage=result.usage,
                cost_usd=self._prices.cost_for(result.model, result.usage),
                latency_ms=_elapsed_ms(started_at),
                fallback_used=was_fallback_used(),
            )
        )
        return result

    async def stream(self, request: CompletionRequest) -> AsyncIterator[StreamEvent]:
        reset_fallback_used()
        started_at = time.perf_counter()
        async for event in self._inner.stream(request):
            if isinstance(event, StreamCompleted):
                # Record before yielding: the consumer may stop iterating right
                # after the terminal event, which would cancel this generator.
                await self._recorder.record(
                    CostEvent(
                        model=event.model,
                        operation=self._operation,
                        usage=event.usage,
                        cost_usd=self._prices.cost_for(event.model, event.usage),
                        latency_ms=_elapsed_ms(started_at),
                        fallback_used=was_fallback_used(),
                    )
                )
            yield event


class MeteredEmbeddingProvider:
    def __init__(
        self,
        inner: EmbeddingProvider,
        *,
        prices: PriceTable,
        recorder: CostRecorder,
    ) -> None:
        self._inner = inner
        self._prices = prices
        self._recorder = recorder

    @property
    def dimensions(self) -> int:
        return self._inner.dimensions

    async def embed_batch(self, texts: Sequence[str]) -> EmbeddingBatch:
        started_at = time.perf_counter()
        batch = await self._inner.embed_batch(texts)
        await self._recorder.record(
            CostEvent(
                model=batch.model,
                operation="embedding",
                usage=batch.usage,
                cost_usd=self._prices.cost_for(batch.model, batch.usage),
                latency_ms=_elapsed_ms(started_at),
            )
        )
        return batch


class MeteredReranker:
    """Reranker decorator. Hosted rerankers bill per request, not per token, so
    the event carries zero usage and zero cost — it exists for latency and call
    counting on the dashboard."""

    def __init__(self, inner: Reranker, *, recorder: CostRecorder) -> None:
        self._inner = inner
        self._recorder = recorder

    @property
    def name(self) -> str:
        return self._inner.name

    async def rerank(
        self, query: str, candidates: Sequence[RerankCandidate], *, top_k: int
    ) -> list[RerankedItem]:
        started_at = time.perf_counter()
        items = await self._inner.rerank(query, candidates, top_k=top_k)
        await self._recorder.record(
            CostEvent(
                model=ModelRef(provider="rerank", name=self._inner.name),
                operation="rerank",
                usage=TokenUsage(),
                cost_usd=_ZERO_USD,
                latency_ms=_elapsed_ms(started_at),
            )
        )
        return items
