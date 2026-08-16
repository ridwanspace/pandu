"""ReembedDocuments: embedding-model migration without re-parsing."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.modules.documents.application.use_cases import ReembedDocuments
from app.modules.documents.domain.entities import Chunk, Document, DocumentStatus
from app.shared.domain.errors import NotFoundError
from tests.unit.documents.fakes import FakeChunkRepository, FakeDocumentRepository, FakeEmbedder


def _document(status: DocumentStatus = DocumentStatus.READY) -> Document:
    now = datetime.now(UTC)
    return Document(
        id=uuid4(),
        filename="doc.md",
        content_type="text/markdown",
        size_bytes=100,
        status=status,
        created_at=now,
        updated_at=now,
    )


def _chunks(document: Document, count: int) -> list[Chunk]:
    return [
        Chunk(document_id=document.id, seq=seq, text=f"chunk {seq} text", token_count=3)
        for seq in range(count)
    ]


def _use_case(
    documents: FakeDocumentRepository,
    chunks: FakeChunkRepository,
    embedder: FakeEmbedder,
    *,
    batch_size: int = 2,
) -> ReembedDocuments:
    return ReembedDocuments(
        documents=documents,
        chunks=chunks,
        embedder=embedder,
        embed_batch_size=batch_size,
    )


async def test_reembeds_all_ready_documents_in_batches() -> None:
    documents, chunks, embedder = FakeDocumentRepository(), FakeChunkRepository(), FakeEmbedder()
    first, second = _document(), _document()
    for doc, n in ((first, 3), (second, 1)):
        await documents.add(doc)
        chunks.stored[doc.id] = _chunks(doc, n)
        chunks.embeddings[doc.id] = [(0.0, 0.0, 0.0)] * n

    report = await _use_case(documents, chunks, embedder)()

    assert (report.documents, report.chunks, report.skipped) == (2, 4, 0)
    # Batch size 2 over 3 chunks -> calls of 2 and 1; the single-chunk doc adds 1.
    assert sorted(embedder.batch_sizes) == [1, 1, 2]
    # New vectors encode text length (FakeEmbedder) — the old zeros are gone,
    # aligned with seq order.
    assert chunks.embeddings[first.id] == [
        (float(len(c.text)), 0.0, 1.0) for c in chunks.stored[first.id]
    ]


async def test_skips_non_ready_documents_and_empty_documents() -> None:
    documents, chunks, embedder = FakeDocumentRepository(), FakeChunkRepository(), FakeEmbedder()
    failed = _document(DocumentStatus.FAILED)
    empty = _document()
    await documents.add(failed)
    await documents.add(empty)

    report = await _use_case(documents, chunks, embedder)()

    assert (report.documents, report.chunks, report.skipped) == (0, 0, 2)
    assert embedder.batch_sizes == []


async def test_single_document_scope() -> None:
    documents, chunks, embedder = FakeDocumentRepository(), FakeChunkRepository(), FakeEmbedder()
    target, other = _document(), _document()
    for doc in (target, other):
        await documents.add(doc)
        chunks.stored[doc.id] = _chunks(doc, 2)
        chunks.embeddings[doc.id] = [(0.0, 0.0, 0.0)] * 2

    report = await _use_case(documents, chunks, embedder)(target.id)

    assert (report.documents, report.chunks) == (1, 2)
    assert chunks.embeddings[other.id] == [(0.0, 0.0, 0.0)] * 2


async def test_unknown_document_raises() -> None:
    documents, chunks, embedder = FakeDocumentRepository(), FakeChunkRepository(), FakeEmbedder()
    with pytest.raises(NotFoundError):
        await _use_case(documents, chunks, embedder)(uuid4())
