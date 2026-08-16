"""Retrieval module — domain entities.

Deliberately independent of the documents module (import-linter enforced):
retrieval reads the same chunk store through its own SearchIndex port.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class ScoredChunk:
    """One candidate from a single search arm (dense OR lexical)."""

    chunk_id: UUID
    document_id: UUID
    seq: int
    text: str
    filename: str
    heading_path: tuple[str, ...]
    score: float


@dataclass(frozen=True, slots=True)
class RankedChunk:
    """A chunk after fusion (and optional reranking), ready for prompting."""

    chunk_id: UUID
    document_id: UUID
    seq: int
    text: str
    filename: str
    heading_path: tuple[str, ...]
    fused_score: float
    rerank_score: float | None = None
    dense_rank: int | None = None
    lexical_rank: int | None = None
