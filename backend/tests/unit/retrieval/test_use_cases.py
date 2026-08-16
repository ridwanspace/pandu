"""RetrieveContext unit tests — hand-written fakes for every port, no I/O."""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from uuid import UUID

import pytest

from app.modules.retrieval.application.dto import RetrievalQuery
from app.modules.retrieval.application.use_cases import RetrieveContext
from app.modules.retrieval.domain.entities import ScoredChunk
from app.modules.retrieval.domain.search_index import SearchIndex
from app.shared.domain.errors import InvalidInputError
from app.shared.domain.ports.embeddings import EmbeddingBatch
from app.shared.domain.ports.reranker import RerankCandidate, RerankedItem
from app.shared.domain.values import ModelRef, TokenUsage

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    from app.shared.domain.ports.tracing import TraceSpan


def chunk(n: int, *, text: str | None = None) -> ScoredChunk:
    return ScoredChunk(
        chunk_id=UUID(int=n),
        document_id=UUID(int=1000 + n),
        seq=n,
        text=text if text is not None else f"chunk text {n}",
        filename="doc.md",
        heading_path=("Intro",),
        score=0.5,
    )


class FakeEmbedder:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    @property
    def dimensions(self) -> int:
        return 3

    async def embed_batch(self, texts: Sequence[str]) -> EmbeddingBatch:
        self.calls.append(list(texts))
        return EmbeddingBatch(
            vectors=tuple((1.0, 0.0, 0.0) for _ in texts),
            usage=TokenUsage(prompt_tokens=4),
            model=ModelRef(provider="fake", name="embed-1"),
        )


@dataclass
class SearchCall:
    limit: int
    document_ids: tuple[UUID, ...] | None


class FakeIndex:
    def __init__(
        self,
        dense: list[ScoredChunk] | None = None,
        lexical: list[ScoredChunk] | None = None,
        *,
        require_concurrency: bool = False,
    ) -> None:
        self._dense = dense or []
        self._lexical = lexical or []
        self.dense_calls: list[SearchCall] = []
        self.lexical_calls: list[SearchCall] = []
        # Both arms must reach this barrier before either returns: a sequential
        # implementation deadlocks (caught by wait_for in the test).
        self._barrier = asyncio.Barrier(2) if require_concurrency else None

    async def dense_search(
        self,
        embedding: Sequence[float],
        *,
        limit: int,
        document_ids: Sequence[UUID] | None = None,
    ) -> list[ScoredChunk]:
        self.dense_calls.append(
            SearchCall(limit, tuple(document_ids) if document_ids is not None else None)
        )
        if self._barrier is not None:
            await self._barrier.wait()
        return self._dense[:limit]

    async def lexical_search(
        self,
        query: str,
        *,
        limit: int,
        document_ids: Sequence[UUID] | None = None,
    ) -> list[ScoredChunk]:
        self.lexical_calls.append(
            SearchCall(limit, tuple(document_ids) if document_ids is not None else None)
        )
        if self._barrier is not None:
            await self._barrier.wait()
        return self._lexical[:limit]


class FakeReranker:
    """Reverses candidate order so tests can tell fused order from reranked."""

    def __init__(self, name: str = "fake-cross-encoder") -> None:
        self._name = name
        self.calls: list[tuple[str, list[RerankCandidate], int]] = []

    @property
    def name(self) -> str:
        return self._name

    async def rerank(
        self, query: str, candidates: Sequence[RerankCandidate], *, top_k: int
    ) -> list[RerankedItem]:
        self.calls.append((query, list(candidates), top_k))
        selected = list(candidates)[::-1][:top_k]
        return [
            RerankedItem(id=c.id, score=float(len(selected) - i)) for i, c in enumerate(selected)
        ]


class NoopReranker:
    @property
    def name(self) -> str:
        return "none"

    async def rerank(
        self, query: str, candidates: Sequence[RerankCandidate], *, top_k: int
    ) -> list[RerankedItem]:
        raise AssertionError("no-op reranker must never be invoked")


class FakeSpan:
    def __init__(self, name: str) -> None:
        self.name = name
        self.attributes: dict[str, object] = {}

    def annotate(self, **attributes: object) -> None:
        self.attributes.update(attributes)


class FakeTracer:
    def __init__(self) -> None:
        self.spans: list[FakeSpan] = []

    @contextmanager
    def span(
        self, name: str, *, trace_id: str | None = None, **attributes: object
    ) -> Iterator[TraceSpan]:
        span = FakeSpan(name)
        span.attributes.update(attributes)
        self.spans.append(span)
        yield span

    def flush(self) -> None:  # pragma: no cover - protocol completeness
        pass


@dataclass
class Harness:
    embedder: FakeEmbedder = field(default_factory=FakeEmbedder)
    index: FakeIndex = field(default_factory=FakeIndex)
    reranker: FakeReranker | NoopReranker = field(default_factory=NoopReranker)
    tracer: FakeTracer = field(default_factory=FakeTracer)
    candidates: int = 20
    top_k: int = 5
    rrf_k: int = 60

    def use_case(self) -> RetrieveContext:
        return RetrieveContext(
            embedder=self.embedder,
            index=self.index,
            reranker=self.reranker,
            tracer=self.tracer,
            candidates=self.candidates,
            top_k=self.top_k,
            rrf_k=self.rrf_k,
        )


class TestValidation:
    async def test_empty_query_rejected(self) -> None:
        harness = Harness()
        with pytest.raises(InvalidInputError):
            await harness.use_case()(RetrievalQuery(text=""))
        with pytest.raises(InvalidInputError):
            await harness.use_case()(RetrievalQuery(text="   \n\t"))
        assert harness.embedder.calls == []

    def test_constructor_rejects_non_positive_config(self) -> None:
        harness = Harness()
        for bad in ({"candidates": 0}, {"top_k": -1}, {"rrf_k": 0}):
            with pytest.raises(ValueError, match="must be positive"):
                RetrieveContext(
                    embedder=harness.embedder,
                    index=harness.index,
                    reranker=harness.reranker,
                    tracer=harness.tracer,
                    **{"candidates": 20, "top_k": 5, "rrf_k": 60, **bad},
                )


class TestSearch:
    async def test_arms_run_concurrently(self) -> None:
        index = FakeIndex([chunk(1)], [chunk(2)], require_concurrency=True)
        harness = Harness(index=index)

        context = await asyncio.wait_for(
            harness.use_case()(RetrievalQuery(text="what is RRF?")), timeout=5
        )

        assert context.candidate_count == 2

    async def test_honors_candidates_limit_and_document_filter(self) -> None:
        doc_ids = (UUID(int=501), UUID(int=502))
        index = FakeIndex([chunk(i) for i in range(1, 10)], [chunk(i) for i in range(5, 15)])
        harness = Harness(index=index, candidates=7)

        await harness.use_case()(RetrievalQuery(text="q", document_ids=doc_ids))

        assert index.dense_calls == [SearchCall(limit=7, document_ids=doc_ids)]
        assert index.lexical_calls == [SearchCall(limit=7, document_ids=doc_ids)]

    async def test_no_document_filter_passes_none(self) -> None:
        index = FakeIndex([chunk(1)], [])
        harness = Harness(index=index)

        await harness.use_case()(RetrievalQuery(text="q"))

        assert index.dense_calls[0].document_ids is None
        assert index.lexical_calls[0].document_ids is None


class TestNoopRerankerPath:
    async def test_top_k_slice_of_fused_order_with_no_rerank_score(self) -> None:
        dense = [chunk(i) for i in range(1, 8)]
        lexical = [chunk(i) for i in range(4, 11)]
        harness = Harness(index=FakeIndex(dense, lexical), top_k=3)

        context = await harness.use_case()(RetrievalQuery(text="q"))

        assert len(context.chunks) == 3
        assert context.reranker == "none"
        assert all(c.rerank_score is None for c in context.chunks)
        # overlapping chunks (in both arms) outrank single-arm hits under RRF
        assert {c.chunk_id for c in context.chunks} <= {c.chunk_id for c in dense + lexical}
        assert context.candidate_count == len({c.chunk_id for c in dense + lexical})
        assert context.rerank_latency_ms == 0
        # fused order is preserved: scores are non-increasing
        scores = [c.fused_score for c in context.chunks]
        assert scores == sorted(scores, reverse=True)

    async def test_fused_provenance_survives_into_ranked_chunks(self) -> None:
        harness = Harness(index=FakeIndex([chunk(1), chunk(2)], [chunk(2)]), top_k=5)

        context = await harness.use_case()(RetrievalQuery(text="q"))

        by_id = {c.chunk_id: c for c in context.chunks}
        assert (by_id[UUID(int=1)].dense_rank, by_id[UUID(int=1)].lexical_rank) == (1, None)
        assert (by_id[UUID(int=2)].dense_rank, by_id[UUID(int=2)].lexical_rank) == (2, 1)


class TestRerankerPath:
    async def test_reranker_order_and_scores_win(self) -> None:
        reranker = FakeReranker()
        dense = [chunk(1), chunk(2), chunk(3)]
        harness = Harness(index=FakeIndex(dense, []), reranker=reranker, top_k=2)

        context = await harness.use_case()(RetrievalQuery(text="q"))

        assert context.reranker == "fake-cross-encoder"
        # FakeReranker reverses the fused order [1, 2, 3] -> picks [3, 2]
        assert [c.chunk_id for c in context.chunks] == [UUID(int=3), UUID(int=2)]
        assert [c.rerank_score for c in context.chunks] == [2.0, 1.0]
        # fused metadata still attached after reranking
        assert context.chunks[0].dense_rank == 3
        assert context.chunks[0].fused_score == pytest.approx(1 / 63)

    async def test_reranker_receives_all_fused_candidates_and_top_k(self) -> None:
        reranker = FakeReranker()
        dense = [chunk(i, text=f"dense {i}") for i in range(1, 6)]
        lexical = [chunk(i, text=f"lexical {i}") for i in range(4, 9)]
        harness = Harness(index=FakeIndex(dense, lexical), reranker=reranker, top_k=3)

        await harness.use_case()(RetrievalQuery(text="which chunks?"))

        (query, candidates, top_k) = reranker.calls[0]
        assert query == "which chunks?"
        assert top_k == 3
        fused_ids = {str(c.chunk_id) for c in dense + lexical}
        assert {c.id for c in candidates} == fused_ids
        assert all(c.text for c in candidates)

    async def test_empty_results_skip_reranker(self) -> None:
        reranker = FakeReranker()
        harness = Harness(index=FakeIndex([], []), reranker=reranker)

        context = await harness.use_case()(RetrievalQuery(text="nothing indexed"))

        assert context.chunks == ()
        assert context.candidate_count == 0
        assert reranker.calls == []
        assert context.rerank_latency_ms == 0


class TestObservability:
    async def test_timings_are_non_negative_ints(self) -> None:
        harness = Harness(index=FakeIndex([chunk(1)], [chunk(2)]), reranker=FakeReranker())

        context = await harness.use_case()(RetrievalQuery(text="q"))

        for value in (
            context.embed_latency_ms,
            context.search_latency_ms,
            context.rerank_latency_ms,
        ):
            assert isinstance(value, int)
            assert value >= 0

    async def test_spans_cover_phases_and_never_carry_chunk_text(self) -> None:
        secret = "TOP-SECRET chunk body that must never reach the tracer"
        index = FakeIndex([chunk(1, text=secret)], [chunk(2, text=secret)])
        harness = Harness(index=index, reranker=FakeReranker(), tracer=FakeTracer())

        await harness.use_case()(RetrievalQuery(text="q"), trace_id="trace-123")

        names = [s.name for s in harness.tracer.spans]
        assert names == ["retrieval.embed", "retrieval.search", "retrieval.rerank"]
        for span in harness.tracer.spans:
            assert secret not in repr(span.attributes)

    async def test_search_span_reports_counts(self) -> None:
        harness = Harness(index=FakeIndex([chunk(1), chunk(2)], [chunk(2)]))

        await harness.use_case()(RetrievalQuery(text="q"))

        search_span = next(s for s in harness.tracer.spans if s.name == "retrieval.search")
        assert search_span.attributes["dense_count"] == 2
        assert search_span.attributes["lexical_count"] == 1
        assert search_span.attributes["fused_count"] == 2


def test_fake_index_conforms_to_the_search_index_port() -> None:
    """Structural conformance, enforced by mypy on this assignment: the fake
    every test runs against must match the SearchIndex protocol exactly."""
    index: SearchIndex = FakeIndex()
    assert index is not None
