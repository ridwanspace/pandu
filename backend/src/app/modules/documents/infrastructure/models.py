"""Documents module — SQLAlchemy models (documents, document_blobs, chunks).

The retrieval module queries ``chunks`` with textual SQL only and never
imports these classes (module independence, ADR-001). Index DDL is defined
here so Alembic autogenerate picks it up; migrations are created centrally.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Computed,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import BYTEA, JSONB, TSVECTOR
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.infrastructure.db.base import Base

EMBEDDING_DIMENSIONS = 1536


class DocumentModel(Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    filename: Mapped[str] = mapped_column(String(512))
    content_type: Mapped[str] = mapped_column(String(128))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(32))
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    chunk_params: Mapped[dict[str, int]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class DocumentBlobModel(Base):
    """Raw upload payload, handed to the worker via the DB (no shared volume)."""

    __tablename__ = "document_blobs"

    document_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        primary_key=True,
    )
    content: Mapped[bytes] = mapped_column(BYTEA)


class ChunkModel(Base):
    __tablename__ = "chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "seq"),
        Index(
            "ix_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        Index("ix_chunks_tsv_gin", "tsv", postgresql_using="gin"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    document_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        index=True,
    )
    seq: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    token_count: Mapped[int] = mapped_column(Integer)
    heading_path: Mapped[list[str]] = mapped_column(JSONB, default=list)
    embedding: Mapped[Any] = mapped_column(Vector(EMBEDDING_DIMENSIONS))
    # Lexical arm of hybrid search: generated column, indexed with GIN above.
    tsv: Mapped[Any] = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('english', text)", persisted=True),
    )
