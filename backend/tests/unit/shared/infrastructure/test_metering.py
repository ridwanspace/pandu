"""Metering decorators: correct CostEvent per call, streaming emission timing,
and the fallback flag handoff."""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from app.shared.domain.ports.embeddings import EmbeddingBatch
from app.shared.domain.ports.llm import StreamCompleted
from app.shared.domain.ports.reranker import RerankCandidate, RerankedItem
from app.shared.domain.values import ModelRef, TokenUsage
from app.shared.infrastructure.ai.fallback import FallbackLLMProvider
from app.shared.infrastructure.ai.metering import (
    MeteredEmbeddingProvider,
    MeteredLLMProvider,
    MeteredReranker,
)
from app.shared.infrastructure.ai.pricing import PriceTable
from tests.unit.shared.infrastructure.fakes import (
    FakeCostRecorder,
    FakeLLMProvider,
    collect_events,
    make_request,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

from app.shared.domain.errors import ProviderError

MODEL = ModelRef(provider="openai", name="gpt-4o-mini")
USAGE = TokenUsage(prompt_tokens=1000, completion_tokens=500)
EXPECTED_COST = Decimal("0.000450")


class TestMeteredLLMProvider:
    async def test_complete_emits_one_event(self) -> None:
        recorder = FakeCostRecorder()
        provider = MeteredLLMProvider(
            FakeLLMProvider(model=MODEL, usage=USAGE),
            prices=PriceTable(),
            recorder=recorder,
        )

        result = await provider.complete(make_request())

        assert result.usage == USAGE
        assert len(recorder.events) == 1
        event = recorder.events[0]
        assert event.model == MODEL
        assert event.operation == "chat"
        assert event.usage == USAGE
        assert event.cost_usd == EXPECTED_COST
        assert event.latency_ms >= 0
        assert event.fallback_used is False

    async def test_judge_operation_is_configurable(self) -> None:
        recorder = FakeCostRecorder()
        provider = MeteredLLMProvider(
            FakeLLMProvider(model=MODEL, usage=USAGE),
            prices=PriceTable(),
            recorder=recorder,
            operation="judge",
        )
        await provider.complete(make_request())
        assert recorder.events[0].operation == "judge"

    async def test_fallback_flag_reaches_event(self) -> None:
        secondary_model = ModelRef(provider="gemini", name="gemini-2.0-flash")
        chain = FallbackLLMProvider(
            [
                (
                    MODEL,
                    FakeLLMProvider(
                        model=MODEL,
                        error=ProviderError(
                            "down", provider="openai", model=MODEL.name, retryable=True
                        ),
                    ),
                ),
                (secondary_model, FakeLLMProvider(model=secondary_model, usage=USAGE)),
            ]
        )
        recorder = FakeCostRecorder()
        provider = MeteredLLMProvider(chain, prices=PriceTable(), recorder=recorder)

        await provider.complete(make_request())

        event = recorder.events[0]
        assert event.fallback_used is True
        assert event.model == secondary_model  # billed against the model that answered

    async def test_stream_emits_event_on_completion(self) -> None:
        recorder = FakeCostRecorder()
        provider = MeteredLLMProvider(
            FakeLLMProvider(model=MODEL, text="a b c", usage=USAGE),
            prices=PriceTable(),
            recorder=recorder,
        )

        stream = provider.stream(make_request())
        events = []
        async for event in stream:
            # No cost event may exist before the terminal stream event.
            if not isinstance(event, StreamCompleted):
                assert recorder.events == []
            events.append(event)

        assert isinstance(events[-1], StreamCompleted)
        assert len(recorder.events) == 1
        assert recorder.events[0].usage == USAGE
        assert recorder.events[0].cost_usd == EXPECTED_COST

    async def test_stream_passes_events_through_unchanged(self) -> None:
        inner = FakeLLMProvider(model=MODEL, text="x y", usage=USAGE)
        provider = MeteredLLMProvider(inner, prices=PriceTable(), recorder=FakeCostRecorder())
        metered_events = await collect_events(provider.stream(make_request()))
        raw_events = await collect_events(inner.stream(make_request()))
        assert metered_events == raw_events


class TestMeteredEmbeddingProvider:
    async def test_emits_embedding_event(self) -> None:
        model = ModelRef(provider="openai", name="text-embedding-3-small")

        class FakeEmbeddings:
            @property
            def dimensions(self) -> int:
                return 4

            async def embed_batch(self, texts: Sequence[str]) -> EmbeddingBatch:
                return EmbeddingBatch(
                    vectors=tuple((0.0,) * 4 for _ in texts),
                    usage=TokenUsage(prompt_tokens=1_000_000),
                    model=model,
                )

        recorder = FakeCostRecorder()
        provider = MeteredEmbeddingProvider(
            FakeEmbeddings(), prices=PriceTable(), recorder=recorder
        )

        batch = await provider.embed_batch(["a", "b"])

        assert provider.dimensions == 4
        assert len(batch.vectors) == 2
        event = recorder.events[0]
        assert event.operation == "embedding"
        assert event.cost_usd == Decimal("0.02")
        assert event.fallback_used is False


class TestMeteredReranker:
    async def test_emits_zero_cost_rerank_event(self) -> None:
        class FakeReranker:
            @property
            def name(self) -> str:
                return "cohere"

            async def rerank(
                self, query: str, candidates: Sequence[RerankCandidate], *, top_k: int
            ) -> list[RerankedItem]:
                return [RerankedItem(id=c.id, score=1.0) for c in candidates[:top_k]]

        recorder = FakeCostRecorder()
        reranker = MeteredReranker(FakeReranker(), recorder=recorder)

        items = await reranker.rerank(
            "q", [RerankCandidate(id="1", text="t"), RerankCandidate(id="2", text="u")], top_k=1
        )

        assert reranker.name == "cohere"
        assert [item.id for item in items] == ["1"]
        event = recorder.events[0]
        assert event.operation == "rerank"
        assert event.cost_usd == Decimal("0")
        assert event.usage == TokenUsage()
        assert event.model == ModelRef(provider="rerank", name="cohere")
