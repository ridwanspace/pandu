"""Postgres adapters of the documents module against a real database:
repository round-trips, atomic chunk replacement, blob storage, and the
ON DELETE CASCADE wiring the delete flow relies on.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text

from app.modules.documents.domain.entities import Chunk, Document, DocumentStatus
from app.modules.documents.infrastructure.repositories import (
    PostgresBlobStore,
    PostgresChunkRepository,
    PostgresDocumentRepository,
)
from app.shared.domain.errors import NotFoundError
from tests.integration.support import SessionFactory, make_document, vector_at


def _chunks_for(document: Document, texts: list[str]) -> list[Chunk]:
    return [
        Chunk(
            document_id=document.id,
            seq=seq,
            text=chunk_text,
            token_count=len(chunk_text.split()),
            heading_path=("Guide", f"Section {seq}"),
        )
        for seq, chunk_text in enumerate(texts)
    ]


async def _count(session_factory: SessionFactory, sql: str, **params: object) -> int:
    async with session_factory() as session:
        result = await session.execute(text(sql), params)
        return int(result.scalar_one())


class TestDocumentRepository:
    async def test_add_get_roundtrip(self, session_factory: SessionFactory) -> None:
        repo = PostgresDocumentRepository(session_factory)
        document = make_document(filename="handbook.md")

        await repo.add(document)
        loaded = await repo.get(document.id)

        assert loaded is not None
        assert loaded.id == document.id
        assert loaded.filename == "handbook.md"
        assert loaded.content_type == "text/markdown"
        assert loaded.status is DocumentStatus.READY
        assert loaded.error is None
        assert loaded.chunk_params == {"max_tokens": 512, "overlap_tokens": 64}
        assert loaded.created_at == document.created_at
        assert loaded.created_at.tzinfo is not None

    async def test_get_missing_returns_none(self, session_factory: SessionFactory) -> None:
        repo = PostgresDocumentRepository(session_factory)
        assert await repo.get(uuid4()) is None

    async def test_list_all_orders_newest_first(self, session_factory: SessionFactory) -> None:
        repo = PostgresDocumentRepository(session_factory)
        base = datetime.now(UTC)
        oldest = make_document(filename="a.md", created_at=base - timedelta(minutes=2))
        middle = make_document(filename="b.md", created_at=base - timedelta(minutes=1))
        newest = make_document(filename="c.md", created_at=base)
        for document in (middle, newest, oldest):
            await repo.add(document)

        listed = await repo.list_all()

        assert [d.id for d in listed] == [newest.id, middle.id, oldest.id]

    async def test_set_status_updates_error_and_chunk_count(
        self, session_factory: SessionFactory
    ) -> None:
        repo = PostgresDocumentRepository(session_factory)
        document = make_document(status=DocumentStatus.QUEUED)
        await repo.add(document)

        await repo.set_status(document.id, DocumentStatus.FAILED, error="parser exploded")
        failed = await repo.get(document.id)
        assert failed is not None
        assert failed.status is DocumentStatus.FAILED
        assert failed.error == "parser exploded"
        assert failed.updated_at > document.updated_at

        await repo.set_status(document.id, DocumentStatus.READY, chunk_count=7)
        ready = await repo.get(document.id)
        assert ready is not None
        assert ready.status is DocumentStatus.READY
        assert ready.error is None  # a successful transition clears the error
        assert ready.chunk_count == 7

    async def test_delete_removes_row_and_tolerates_missing(
        self, session_factory: SessionFactory
    ) -> None:
        repo = PostgresDocumentRepository(session_factory)
        document = make_document()
        await repo.add(document)

        await repo.delete(document.id)
        assert await repo.get(document.id) is None
        await repo.delete(document.id)  # idempotent


class TestChunkRepository:
    async def test_replace_twice_keeps_count_correct(self, session_factory: SessionFactory) -> None:
        documents = PostgresDocumentRepository(session_factory)
        chunks = PostgresChunkRepository(session_factory)
        document = make_document()
        await documents.add(document)

        first = _chunks_for(document, ["alpha text", "beta text", "gamma text"])
        await chunks.replace_for_document(document.id, first, [vector_at(i / 10) for i in range(3)])
        assert (
            await _count(
                session_factory,
                "SELECT count(*) FROM chunks WHERE document_id = :doc",
                doc=document.id,
            )
            == 3
        )

        second = _chunks_for(document, ["delta text", "epsilon text"])
        await chunks.replace_for_document(document.id, second, [vector_at(0.5), vector_at(0.6)])

        assert (
            await _count(
                session_factory,
                "SELECT count(*) FROM chunks WHERE document_id = :doc",
                doc=document.id,
            )
            == 2
        )
        preview = await chunks.preview_for_document(document.id)
        assert [c.text for c in preview] == ["delta text", "epsilon text"]
        assert [c.seq for c in preview] == [0, 1]
        assert preview[0].heading_path == ("Guide", "Section 0")

    async def test_embeddings_stored_as_1536_dim_vectors(
        self, session_factory: SessionFactory
    ) -> None:
        documents = PostgresDocumentRepository(session_factory)
        chunks = PostgresChunkRepository(session_factory)
        document = make_document()
        await documents.add(document)
        await chunks.replace_for_document(
            document.id, _chunks_for(document, ["only chunk"]), [vector_at(0.25)]
        )

        async with session_factory() as session:
            row = (
                await session.execute(
                    text(
                        "SELECT vector_dims(embedding),"
                        " 1 - (embedding <=> CAST(:probe AS vector))"
                        " FROM chunks WHERE document_id = :doc"
                    ),
                    {"doc": document.id, "probe": str(list(vector_at(0.25)))},
                )
            ).one()
        assert int(row[0]) == 1536
        assert float(row[1]) == pytest.approx(1.0, abs=1e-6)  # stored losslessly

    async def test_replace_with_mismatched_embeddings_raises(
        self, session_factory: SessionFactory
    ) -> None:
        chunks = PostgresChunkRepository(session_factory)
        document = make_document()
        with pytest.raises(ValueError, match="mismatch"):
            await chunks.replace_for_document(
                document.id, _chunks_for(document, ["a", "b"]), [vector_at(0.0)]
            )

    async def test_preview_orders_by_seq_and_limits(self, session_factory: SessionFactory) -> None:
        documents = PostgresDocumentRepository(session_factory)
        chunks = PostgresChunkRepository(session_factory)
        document = make_document()
        await documents.add(document)
        texts = [f"chunk number {i}" for i in range(5)]
        await chunks.replace_for_document(
            document.id, _chunks_for(document, texts), [vector_at(i / 10) for i in range(5)]
        )

        preview = await chunks.preview_for_document(document.id, limit=3)

        assert [c.seq for c in preview] == [0, 1, 2]


class TestBlobStore:
    async def test_put_get_roundtrip_and_overwrite(self, session_factory: SessionFactory) -> None:
        documents = PostgresDocumentRepository(session_factory)
        blobs = PostgresBlobStore(session_factory)
        document = make_document()
        await documents.add(document)

        await blobs.put(document.id, b"first payload \x00\xff")
        assert await blobs.get(document.id) == b"first payload \x00\xff"

        await blobs.put(document.id, b"second payload")  # upsert, not duplicate
        assert await blobs.get(document.id) == b"second payload"

    async def test_get_missing_raises_not_found(self, session_factory: SessionFactory) -> None:
        blobs = PostgresBlobStore(session_factory)
        with pytest.raises(NotFoundError):
            await blobs.get(uuid4())

    async def test_delete_removes_blob(self, session_factory: SessionFactory) -> None:
        documents = PostgresDocumentRepository(session_factory)
        blobs = PostgresBlobStore(session_factory)
        document = make_document()
        await documents.add(document)
        await blobs.put(document.id, b"payload")

        await blobs.delete(document.id)

        with pytest.raises(NotFoundError):
            await blobs.get(document.id)


async def test_deleting_document_cascades_to_chunks_and_blob(
    session_factory: SessionFactory,
) -> None:
    documents = PostgresDocumentRepository(session_factory)
    chunks = PostgresChunkRepository(session_factory)
    blobs = PostgresBlobStore(session_factory)
    document = make_document()
    await documents.add(document)
    await blobs.put(document.id, b"payload")
    await chunks.replace_for_document(
        document.id, _chunks_for(document, ["one", "two"]), [vector_at(0.1), vector_at(0.2)]
    )

    await documents.delete(document.id)

    assert (
        await _count(
            session_factory, "SELECT count(*) FROM chunks WHERE document_id = :doc", doc=document.id
        )
        == 0
    )
    assert (
        await _count(
            session_factory,
            "SELECT count(*) FROM document_blobs WHERE document_id = :doc",
            doc=document.id,
        )
        == 0
    )
