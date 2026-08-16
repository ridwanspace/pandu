"""Postgres-backed SearchIndex: pgvector HNSW (dense) + FTS ``tsvector`` (lexical).

Deliberately textual SQL: the ``chunks`` / ``documents`` tables are owned by the
documents module, and importing its ORM models here would couple the modules
(import-linter forbids it). The two queries below ARE the retrieval engine —
keeping them visible as SQL is the point.

Both arms only see chunks of documents in status ``ready``, so a half-ingested
document can never leak partial context into an answer.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from sqlalchemy import text

from app.modules.retrieval.domain.entities import ScoredChunk

if TYPE_CHECKING:
    from collections.abc import Sequence
    from uuid import UUID

    from sqlalchemy import RowMapping
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_DENSE_SQL = """
SELECT c.id, c.document_id, c.seq, c.text, c.heading_path, d.filename,
       1 - (c.embedding <=> CAST(:emb AS vector)) AS score
FROM chunks c
JOIN documents d ON d.id = c.document_id
WHERE d.status = 'ready'
ORDER BY c.embedding <=> CAST(:emb AS vector)
LIMIT :limit
"""

_DENSE_SQL_FILTERED = """
SELECT c.id, c.document_id, c.seq, c.text, c.heading_path, d.filename,
       1 - (c.embedding <=> CAST(:emb AS vector)) AS score
FROM chunks c
JOIN documents d ON d.id = c.document_id
WHERE d.status = 'ready' AND c.document_id = ANY(:ids)
ORDER BY c.embedding <=> CAST(:emb AS vector)
LIMIT :limit
"""

# ``websearch_to_tsquery`` accepts raw user input safely (no tsquery syntax
# errors on quotes/operators); the CROSS JOIN names the parsed query once so
# match and rank share it.
_LEXICAL_SQL = """
SELECT c.id, c.document_id, c.seq, c.text, c.heading_path, d.filename,
       ts_rank_cd(c.tsv, query) AS score
FROM chunks c
JOIN documents d ON d.id = c.document_id
CROSS JOIN websearch_to_tsquery('english', :q) AS query
WHERE d.status = 'ready' AND c.tsv @@ query
ORDER BY score DESC, c.id
LIMIT :limit
"""

_LEXICAL_SQL_FILTERED = """
SELECT c.id, c.document_id, c.seq, c.text, c.heading_path, d.filename,
       ts_rank_cd(c.tsv, query) AS score
FROM chunks c
JOIN documents d ON d.id = c.document_id
CROSS JOIN websearch_to_tsquery('english', :q) AS query
WHERE d.status = 'ready' AND c.tsv @@ query AND c.document_id = ANY(:ids)
ORDER BY score DESC, c.id
LIMIT :limit
"""


def _to_vector_literal(embedding: Sequence[float]) -> str:
    """pgvector's text input format: ``[0.1,0.2,...]`` (cast server-side)."""
    return "[" + ",".join(map(str, embedding)) + "]"


def _to_heading_path(raw: Any) -> tuple[str, ...]:
    """``heading_path`` is a jsonb array; asyncpg may hand it back decoded or
    as raw JSON text depending on registered codecs — accept both."""
    value = json.loads(raw) if isinstance(raw, str) else raw
    if value is None:
        return ()
    return tuple(str(part) for part in value)


def _to_scored_chunk(row: RowMapping) -> ScoredChunk:
    return ScoredChunk(
        chunk_id=row["id"],
        document_id=row["document_id"],
        seq=row["seq"],
        text=row["text"],
        filename=row["filename"],
        heading_path=_to_heading_path(row["heading_path"]),
        score=float(row["score"]),
    )


class PostgresSearchIndex:
    """SearchIndex adapter over the shared Postgres. One short-lived session
    per call: searches are read-only and must not share transaction state."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def dense_search(
        self,
        embedding: Sequence[float],
        *,
        limit: int,
        document_ids: Sequence[UUID] | None = None,
    ) -> list[ScoredChunk]:
        params: dict[str, Any] = {"emb": _to_vector_literal(embedding), "limit": limit}
        sql = _DENSE_SQL
        if document_ids is not None:
            sql = _DENSE_SQL_FILTERED
            params["ids"] = list(document_ids)
        return await self._run(sql, params)

    async def lexical_search(
        self,
        query: str,
        *,
        limit: int,
        document_ids: Sequence[UUID] | None = None,
    ) -> list[ScoredChunk]:
        params: dict[str, Any] = {"q": query, "limit": limit}
        sql = _LEXICAL_SQL
        if document_ids is not None:
            sql = _LEXICAL_SQL_FILTERED
            params["ids"] = list(document_ids)
        return await self._run(sql, params)

    async def _run(self, sql: str, params: dict[str, Any]) -> list[ScoredChunk]:
        async with self._session_factory() as session:
            result = await session.execute(text(sql), params)
            return [_to_scored_chunk(row) for row in result.mappings()]
