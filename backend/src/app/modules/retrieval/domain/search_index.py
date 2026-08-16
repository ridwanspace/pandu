"""Search index port (ADR-002: pgvector + Postgres FTS behind one seam,
so a Qdrant adapter is a file, not a rewrite)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from app.modules.retrieval.domain.entities import ScoredChunk


class SearchIndex(Protocol):
    async def dense_search(
        self,
        embedding: Sequence[float],
        *,
        limit: int,
        document_ids: Sequence[UUID] | None = None,
    ) -> list[ScoredChunk]: ...

    async def lexical_search(
        self,
        query: str,
        *,
        limit: int,
        document_ids: Sequence[UUID] | None = None,
    ) -> list[ScoredChunk]: ...
