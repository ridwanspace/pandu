"""Retrieval application DTOs — the seam other modules (chat, evaluation)
depend on. Do not rename these types; the import-linter independence contract
explicitly allowlists this seam."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from app.modules.retrieval.domain.entities import RankedChunk


@dataclass(frozen=True, slots=True)
class RetrievalQuery:
    text: str
    document_ids: tuple[UUID, ...] | None = None


@dataclass(frozen=True, slots=True)
class RetrievedContext:
    """Final top-k contexts plus the audit trail the tracer/evals need."""

    chunks: tuple[RankedChunk, ...]
    candidate_count: int
    reranker: str
    embed_latency_ms: int
    search_latency_ms: int
    rerank_latency_ms: int
