"""Shared helpers for the integration and contract suites.

Deterministic embeddings: vectors live on the unit circle spanned by the first
two axes of the 1536-dim space, so the cosine similarity between ``vector_at(a)``
and ``vector_at(b)`` is exactly ``cos(a - b)`` — ordering by angle gives
hand-computable dense-search rankings.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.documents.domain.entities import Document, DocumentStatus
from app.shared.domain.ports.embeddings import EmbeddingBatch
from app.shared.domain.values import ModelRef, TokenUsage

BACKEND_DIR = Path(__file__).resolve().parents[2]
PG_IMAGE = "pgvector/pgvector:pg17"
EMBEDDING_DIM = 1536

SessionFactory = async_sessionmaker[AsyncSession]


def run_migrations(database_url: str) -> None:
    """Apply the real Alembic migrations against ``database_url``.

    The URL is set as the config's main option so ``migrations/env.py`` never
    falls back to the app settings (which would point at the compose stack).
    """
    config = AlembicConfig(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")


def vector_at(angle: float, *, dim: int = EMBEDDING_DIM) -> tuple[float, ...]:
    """Unit vector at ``angle`` radians in the plane of the first two axes."""
    vector = [0.0] * dim
    vector[0] = math.cos(angle)
    vector[1] = math.sin(angle)
    return tuple(vector)


class StaticEmbedder:
    """EmbeddingProvider fake returning one fixed vector for every text."""

    def __init__(self, vector: tuple[float, ...]) -> None:
        self._vector = vector

    @property
    def dimensions(self) -> int:
        return len(self._vector)

    async def embed_batch(self, texts: Sequence[str]) -> EmbeddingBatch:
        return EmbeddingBatch(
            vectors=tuple(self._vector for _ in texts),
            usage=TokenUsage(prompt_tokens=len(texts)),
            model=ModelRef(provider="fake", name="static-embedder"),
        )


class SequenceEmbedder:
    """EmbeddingProvider fake returning a distinct deterministic vector per text
    (stable across batches: the i-th text overall gets ``vector_at(i / 10)``)."""

    def __init__(self, *, dim: int = EMBEDDING_DIM) -> None:
        self._dim = dim
        self._served = 0
        self.batch_sizes: list[int] = []

    @property
    def dimensions(self) -> int:
        return self._dim

    async def embed_batch(self, texts: Sequence[str]) -> EmbeddingBatch:
        self.batch_sizes.append(len(texts))
        vectors = tuple(
            vector_at((self._served + offset) / 10, dim=self._dim) for offset in range(len(texts))
        )
        self._served += len(texts)
        return EmbeddingBatch(
            vectors=vectors,
            usage=TokenUsage(prompt_tokens=len(texts)),
            model=ModelRef(provider="fake", name="sequence-embedder"),
        )


def simple_token_counter(text: str) -> int:
    """Deterministic, offline token counter for the real chunker."""
    return max(1, len(text.split()))


def make_document(
    *,
    filename: str = "doc.md",
    status: DocumentStatus = DocumentStatus.READY,
    created_at: datetime | None = None,
    content_type: str = "text/markdown",
    size_bytes: int = 100,
) -> Document:
    now = created_at or datetime.now(UTC)
    return Document(
        id=uuid4(),
        filename=filename,
        content_type=content_type,
        size_bytes=size_bytes,
        status=status,
        created_at=now,
        updated_at=now,
        chunk_params={"max_tokens": 512, "overlap_tokens": 64},
    )


async def chunk_ids_by_seq(session_factory: SessionFactory, document_id: UUID) -> dict[int, UUID]:
    """The ids the repository generated for a document's chunks, keyed by seq."""
    from sqlalchemy import text as sql_text

    async with session_factory() as session:
        result = await session.execute(
            sql_text("SELECT seq, id FROM chunks WHERE document_id = :doc"),
            {"doc": document_id},
        )
        return {int(seq): chunk_id for seq, chunk_id in result.all()}
