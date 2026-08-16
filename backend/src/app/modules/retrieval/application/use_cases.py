"""Retrieval use case: embed → hybrid search (concurrent) → RRF → rerank.

This is the query-time flow of ARCHITECTURE_REVIEW §3.4. All dependencies are
ports, so the use case is fully exercised by unit tests with in-memory fakes.
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

from app.modules.retrieval.application.dto import RetrievalQuery, RetrievedContext
from app.modules.retrieval.domain.entities import RankedChunk
from app.modules.retrieval.domain.fusion import FusedCandidate, reciprocal_rank_fusion
from app.shared.domain.errors import InvalidInputError

if TYPE_CHECKING:
    from uuid import UUID

    from app.modules.retrieval.domain.search_index import SearchIndex
    from app.shared.domain.ports.embeddings import EmbeddingProvider
    from app.shared.domain.ports.reranker import Reranker
    from app.shared.domain.ports.tracing import Tracer

from app.shared.domain.ports.reranker import RerankCandidate

_NOOP_RERANKER = "none"


def _elapsed_ms(start: float) -> int:
    return round((time.perf_counter() - start) * 1000)


def _to_ranked(candidate: FusedCandidate, *, rerank_score: float | None) -> RankedChunk:
    return RankedChunk(
        chunk_id=candidate.chunk_id,
        document_id=candidate.document_id,
        seq=candidate.seq,
        text=candidate.text,
        filename=candidate.filename,
        heading_path=candidate.heading_path,
        fused_score=candidate.fused_score,
        rerank_score=rerank_score,
        dense_rank=candidate.dense_rank,
        lexical_rank=candidate.lexical_rank,
    )


class RetrieveContext:
    """Turn a user question into the top-k grounded contexts.

    ``candidates`` is the per-arm fan-out (retrieve wide), ``top_k`` the final
    context count (prompt narrow); both are config, not constants, so the eval
    dashboard can sweep them.
    """

    def __init__(
        self,
        *,
        embedder: EmbeddingProvider,
        index: SearchIndex,
        reranker: Reranker,
        tracer: Tracer,
        candidates: int,
        top_k: int,
        rrf_k: int,
    ) -> None:
        if candidates <= 0 or top_k <= 0 or rrf_k <= 0:
            msg = f"candidates, top_k and rrf_k must be positive, got {candidates}/{top_k}/{rrf_k}"
            raise ValueError(msg)
        self._embedder = embedder
        self._index = index
        self._reranker = reranker
        self._tracer = tracer
        self._candidates = candidates
        self._top_k = top_k
        self._rrf_k = rrf_k

    async def __call__(
        self, query: RetrievalQuery, *, trace_id: str | None = None
    ) -> RetrievedContext:
        question = query.text.strip()
        if not question:
            raise InvalidInputError("retrieval query must not be empty")

        embedding, embed_ms = await self._embed(question, trace_id)
        fused, search_ms = await self._search(question, embedding, query.document_ids, trace_id)
        ranked, rerank_ms = await self._rerank(question, fused, trace_id)

        return RetrievedContext(
            chunks=tuple(ranked),
            candidate_count=len(fused),
            reranker=self._reranker.name,
            embed_latency_ms=embed_ms,
            search_latency_ms=search_ms,
            rerank_latency_ms=rerank_ms,
        )

    async def _embed(self, question: str, trace_id: str | None) -> tuple[tuple[float, ...], int]:
        with self._tracer.span("retrieval.embed", trace_id=trace_id) as span:
            started = time.perf_counter()
            batch = await self._embedder.embed_batch([question])
            elapsed = _elapsed_ms(started)
            embedding = batch.vectors[0]
            span.annotate(
                model=str(batch.model),
                dimensions=len(embedding),
                prompt_tokens=batch.usage.prompt_tokens,
                latency_ms=elapsed,
            )
        return embedding, elapsed

    async def _search(
        self,
        question: str,
        embedding: tuple[float, ...],
        document_ids: tuple[UUID, ...] | None,
        trace_id: str | None,
    ) -> tuple[list[FusedCandidate], int]:
        with self._tracer.span("retrieval.search", trace_id=trace_id) as span:
            started = time.perf_counter()
            dense, lexical = await asyncio.gather(
                self._index.dense_search(
                    embedding, limit=self._candidates, document_ids=document_ids
                ),
                self._index.lexical_search(
                    question, limit=self._candidates, document_ids=document_ids
                ),
            )
            fused = reciprocal_rank_fusion([dense, lexical], k=self._rrf_k)
            elapsed = _elapsed_ms(started)
            span.annotate(
                dense_count=len(dense),
                lexical_count=len(lexical),
                fused_count=len(fused),
                rrf_k=self._rrf_k,
                top_fused_scores=[c.fused_score for c in fused[: self._top_k]],
                latency_ms=elapsed,
            )
        return fused, elapsed

    async def _rerank(
        self, question: str, fused: list[FusedCandidate], trace_id: str | None
    ) -> tuple[list[RankedChunk], int]:
        with self._tracer.span("retrieval.rerank", trace_id=trace_id) as span:
            if self._reranker.name == _NOOP_RERANKER or not fused:
                ranked = [
                    _to_ranked(candidate, rerank_score=None) for candidate in fused[: self._top_k]
                ]
                span.annotate(
                    reranker=self._reranker.name,
                    candidate_count=len(fused),
                    returned=len(ranked),
                    latency_ms=0,
                )
                return ranked, 0

            started = time.perf_counter()
            by_id = {str(candidate.chunk_id): candidate for candidate in fused}
            items = await self._reranker.rerank(
                question,
                [RerankCandidate(id=chunk_id, text=c.text) for chunk_id, c in by_id.items()],
                top_k=self._top_k,
            )
            elapsed = _elapsed_ms(started)
            ranked = [
                _to_ranked(by_id[item.id], rerank_score=item.score)
                for item in items
                if item.id in by_id
            ]
            span.annotate(
                reranker=self._reranker.name,
                candidate_count=len(fused),
                returned=len(ranked),
                rerank_scores=[item.score for item in items],
                latency_ms=elapsed,
            )
            return ranked, elapsed
