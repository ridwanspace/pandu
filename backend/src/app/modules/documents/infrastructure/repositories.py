"""Documents module — Postgres adapters for the domain persistence ports.

Each method opens its own session/transaction: use cases compose ports, they
do not manage units of work. Mapping model <-> dataclass is hand-written and
total, so the domain never sees ORM instances.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.documents.domain.entities import Chunk, Document, DocumentStatus
from app.modules.documents.infrastructure.models import (
    ChunkModel,
    DocumentBlobModel,
    DocumentModel,
)
from app.shared.domain.errors import NotFoundError

SessionFactory = async_sessionmaker[AsyncSession]


class PostgresDocumentRepository:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def add(self, document: Document) -> None:
        async with self._session_factory() as session, session.begin():
            session.add(_document_to_model(document))

    async def get(self, document_id: UUID) -> Document | None:
        async with self._session_factory() as session:
            model = await session.get(DocumentModel, document_id)
            return _document_to_domain(model) if model is not None else None

    async def list_all(self) -> list[Document]:
        async with self._session_factory() as session:
            stmt = select(DocumentModel).order_by(DocumentModel.created_at.desc(), DocumentModel.id)
            models = (await session.scalars(stmt)).all()
            return [_document_to_domain(m) for m in models]

    async def set_status(
        self,
        document_id: UUID,
        status: DocumentStatus,
        *,
        error: str | None = None,
        chunk_count: int | None = None,
    ) -> None:
        values: dict[str, Any] = {
            "status": status.value,
            "error": error,
            "updated_at": datetime.now(UTC),
        }
        if chunk_count is not None:
            values["chunk_count"] = chunk_count
        async with self._session_factory() as session, session.begin():
            await session.execute(
                update(DocumentModel).where(DocumentModel.id == document_id).values(**values)
            )

    async def delete(self, document_id: UUID) -> None:
        async with self._session_factory() as session, session.begin():
            await session.execute(delete(DocumentModel).where(DocumentModel.id == document_id))


class PostgresChunkRepository:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def replace_for_document(
        self,
        document_id: UUID,
        chunks: Sequence[Chunk],
        embeddings: Sequence[tuple[float, ...]],
    ) -> None:
        if len(chunks) != len(embeddings):
            msg = f"chunk/embedding count mismatch: {len(chunks)} != {len(embeddings)}"
            raise ValueError(msg)
        # Delete + insert in one transaction: readers never observe a
        # half-replaced chunk set.
        async with self._session_factory() as session, session.begin():
            await session.execute(delete(ChunkModel).where(ChunkModel.document_id == document_id))
            session.add_all(
                ChunkModel(
                    id=uuid4(),
                    document_id=chunk.document_id,
                    seq=chunk.seq,
                    text=chunk.text,
                    token_count=chunk.token_count,
                    heading_path=list(chunk.heading_path),
                    embedding=list(embedding),
                )
                for chunk, embedding in zip(chunks, embeddings, strict=True)
            )

    async def preview_for_document(self, document_id: UUID, *, limit: int = 20) -> list[Chunk]:
        async with self._session_factory() as session:
            stmt = (
                select(ChunkModel)
                .where(ChunkModel.document_id == document_id)
                .order_by(ChunkModel.seq)
                .limit(limit)
            )
            models = (await session.scalars(stmt)).all()
            return [_chunk_to_domain(m) for m in models]


class PostgresBlobStore:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def put(self, document_id: UUID, content: bytes) -> None:
        stmt = pg_insert(DocumentBlobModel).values(document_id=document_id, content=content)
        stmt = stmt.on_conflict_do_update(
            index_elements=[DocumentBlobModel.document_id],
            set_={"content": stmt.excluded.content},
        )
        async with self._session_factory() as session, session.begin():
            await session.execute(stmt)

    async def get(self, document_id: UUID) -> bytes:
        async with self._session_factory() as session:
            model = await session.get(DocumentBlobModel, document_id)
            if model is None:
                raise NotFoundError(f"blob for document {document_id} not found")
            return bytes(model.content)

    async def delete(self, document_id: UUID) -> None:
        async with self._session_factory() as session, session.begin():
            await session.execute(
                delete(DocumentBlobModel).where(DocumentBlobModel.document_id == document_id)
            )


def _document_to_model(document: Document) -> DocumentModel:
    return DocumentModel(
        id=document.id,
        filename=document.filename,
        content_type=document.content_type,
        size_bytes=document.size_bytes,
        status=document.status.value,
        error=document.error,
        chunk_count=document.chunk_count,
        chunk_params=dict(document.chunk_params),
        created_at=document.created_at,
        updated_at=document.updated_at,
    )


def _document_to_domain(model: DocumentModel) -> Document:
    return Document(
        id=model.id,
        filename=model.filename,
        content_type=model.content_type,
        size_bytes=model.size_bytes,
        status=DocumentStatus(model.status),
        error=model.error,
        chunk_count=model.chunk_count,
        chunk_params=dict(model.chunk_params or {}),
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _chunk_to_domain(model: ChunkModel) -> Chunk:
    return Chunk(
        document_id=model.document_id,
        seq=model.seq,
        text=model.text,
        token_count=model.token_count,
        heading_path=tuple(model.heading_path or []),
    )
