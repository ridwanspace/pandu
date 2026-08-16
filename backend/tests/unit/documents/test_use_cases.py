"""Use cases against in-memory fakes: no DB, no network, no mocks."""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.modules.documents.application.use_cases import (
    DeleteDocument,
    GetDocument,
    IngestDocument,
    ListDocuments,
    PreviewChunks,
    UploadDocument,
)
from app.modules.documents.domain.entities import Chunk, DocumentStatus
from app.modules.documents.domain.parser import BlockKind, ParsedBlock
from app.shared.domain.errors import InvalidInputError, NotFoundError
from tests.unit.documents.fakes import (
    FakeBlobStore,
    FakeChunkRepository,
    FakeDocumentRepository,
    FakeEmbedder,
    FakeJobQueue,
    FakeParser,
    count_words,
    make_document,
)


@pytest.fixture
def documents() -> FakeDocumentRepository:
    return FakeDocumentRepository()


@pytest.fixture
def blobs() -> FakeBlobStore:
    return FakeBlobStore()


@pytest.fixture
def jobs() -> FakeJobQueue:
    return FakeJobQueue()


@pytest.fixture
def chunks() -> FakeChunkRepository:
    return FakeChunkRepository()


def build_upload(
    documents: FakeDocumentRepository,
    blobs: FakeBlobStore,
    jobs: FakeJobQueue,
    *,
    max_upload_bytes: int = 1024,
) -> UploadDocument:
    return UploadDocument(
        documents=documents,
        blobs=blobs,
        jobs=jobs,
        max_upload_bytes=max_upload_bytes,
        chunk_max_tokens=64,
        chunk_overlap_tokens=8,
    )


def build_ingest(
    documents: FakeDocumentRepository,
    chunks: FakeChunkRepository,
    blobs: FakeBlobStore,
    parser: FakeParser,
    embedder: FakeEmbedder,
    *,
    embed_batch_size: int = 2,
) -> IngestDocument:
    return IngestDocument(
        documents=documents,
        chunks=chunks,
        blobs=blobs,
        parser=parser,
        embedder=embedder,
        count_tokens=count_words,
        chunk_max_tokens=64,
        chunk_overlap_tokens=8,
        embed_batch_size=embed_batch_size,
    )


class TestUploadDocument:
    async def test_happy_path_stores_queues_and_returns_document(
        self, documents: FakeDocumentRepository, blobs: FakeBlobStore, jobs: FakeJobQueue
    ) -> None:
        upload = build_upload(documents, blobs, jobs)
        document = await upload(
            filename="notes.md", content_type="text/markdown", content=b"# hi\n\nbody\n"
        )
        assert document.status is DocumentStatus.QUEUED
        assert document.size_bytes == len(b"# hi\n\nbody\n")
        assert document.chunk_params == {"max_tokens": 64, "overlap_tokens": 8}
        assert documents.documents[document.id] is document
        assert blobs.blobs[document.id] == b"# hi\n\nbody\n"
        assert jobs.enqueued == [document.id]

    async def test_oversized_upload_is_rejected(
        self, documents: FakeDocumentRepository, blobs: FakeBlobStore, jobs: FakeJobQueue
    ) -> None:
        upload = build_upload(documents, blobs, jobs, max_upload_bytes=10)
        with pytest.raises(InvalidInputError, match="upload limit"):
            await upload(filename="big.txt", content_type="text/plain", content=b"x" * 11)
        assert not documents.documents
        assert not blobs.blobs
        assert not jobs.enqueued

    @pytest.mark.parametrize(
        "content_type", ["application/zip", "image/png", "application/octet-stream"]
    )
    async def test_unsupported_content_type_is_rejected(
        self,
        documents: FakeDocumentRepository,
        blobs: FakeBlobStore,
        jobs: FakeJobQueue,
        content_type: str,
    ) -> None:
        upload = build_upload(documents, blobs, jobs)
        with pytest.raises(InvalidInputError, match="unsupported content type"):
            await upload(filename="f.bin", content_type=content_type, content=b"data")

    async def test_empty_file_and_empty_filename_are_rejected(
        self, documents: FakeDocumentRepository, blobs: FakeBlobStore, jobs: FakeJobQueue
    ) -> None:
        upload = build_upload(documents, blobs, jobs)
        with pytest.raises(InvalidInputError, match="empty"):
            await upload(filename="a.txt", content_type="text/plain", content=b"")
        with pytest.raises(InvalidInputError, match="filename"):
            await upload(filename="   ", content_type="text/plain", content=b"data")


class TestQueries:
    async def test_get_returns_document(self, documents: FakeDocumentRepository) -> None:
        document = make_document()
        await documents.add(document)
        assert await GetDocument(documents=documents)(document.id) is document

    async def test_get_missing_raises(self, documents: FakeDocumentRepository) -> None:
        with pytest.raises(NotFoundError):
            await GetDocument(documents=documents)(uuid4())

    async def test_list_returns_all(self, documents: FakeDocumentRepository) -> None:
        await documents.add(make_document())
        await documents.add(make_document())
        assert len(await ListDocuments(documents=documents)()) == 2

    async def test_preview_chunks_requires_existing_document(
        self, documents: FakeDocumentRepository, chunks: FakeChunkRepository
    ) -> None:
        with pytest.raises(NotFoundError):
            await PreviewChunks(documents=documents, chunks=chunks)(uuid4())

    async def test_preview_chunks_returns_stored_chunks_up_to_limit(
        self, documents: FakeDocumentRepository, chunks: FakeChunkRepository
    ) -> None:
        document = make_document()
        await documents.add(document)
        stored = [
            Chunk(
                document_id=document.id,
                seq=seq,
                text=f"chunk {seq}",
                token_count=2,
                heading_path=("H",),
            )
            for seq in range(3)
        ]
        await chunks.replace_for_document(document.id, stored, [(1.0,)] * 3)

        preview = await PreviewChunks(documents=documents, chunks=chunks)(document.id, limit=2)

        assert preview == stored[:2]


class TestDeleteDocument:
    async def test_removes_document_and_blob(
        self, documents: FakeDocumentRepository, blobs: FakeBlobStore
    ) -> None:
        document = make_document()
        await documents.add(document)
        await blobs.put(document.id, b"payload")
        await DeleteDocument(documents=documents, blobs=blobs)(document.id)
        assert document.id not in documents.documents
        assert document.id not in blobs.blobs

    async def test_missing_document_raises(
        self, documents: FakeDocumentRepository, blobs: FakeBlobStore
    ) -> None:
        with pytest.raises(NotFoundError):
            await DeleteDocument(documents=documents, blobs=blobs)(uuid4())


def blocks_with_headings(count: int) -> list[ParsedBlock]:
    """Blocks under distinct headings so each becomes its own chunk."""
    return [
        ParsedBlock(kind=BlockKind.TEXT, text=f"content number {i}", heading_path=(f"H{i}",))
        for i in range(count)
    ]


class TestIngestDocument:
    async def test_happy_path(
        self,
        documents: FakeDocumentRepository,
        chunks: FakeChunkRepository,
        blobs: FakeBlobStore,
    ) -> None:
        document = make_document()
        await documents.add(document)
        await blobs.put(document.id, b"raw payload")
        embedder = FakeEmbedder()
        ingest = build_ingest(
            documents, chunks, blobs, FakeParser(blocks_with_headings(3)), embedder
        )

        await ingest(document.id)

        assert documents.status_history == [
            DocumentStatus.PARSING,
            DocumentStatus.EMBEDDING,
            DocumentStatus.READY,
        ]
        assert document.status is DocumentStatus.READY
        assert document.error is None
        assert document.chunk_count == 3
        stored = chunks.stored[document.id]
        assert [c.seq for c in stored] == [0, 1, 2]
        assert stored[0].heading_path == ("H0",)
        assert stored[0].text == "§ H0\ncontent number 0"
        assert len(chunks.embeddings[document.id]) == 3

    async def test_embedding_runs_in_configured_batches(
        self,
        documents: FakeDocumentRepository,
        chunks: FakeChunkRepository,
        blobs: FakeBlobStore,
    ) -> None:
        document = make_document()
        await documents.add(document)
        await blobs.put(document.id, b"raw")
        embedder = FakeEmbedder()
        ingest = build_ingest(
            documents,
            chunks,
            blobs,
            FakeParser(blocks_with_headings(5)),
            embedder,
            embed_batch_size=2,
        )
        await ingest(document.id)
        assert embedder.batch_sizes == [2, 2, 1]

    async def test_parser_failure_marks_failed_and_does_not_raise(
        self,
        documents: FakeDocumentRepository,
        chunks: FakeChunkRepository,
        blobs: FakeBlobStore,
    ) -> None:
        document = make_document()
        await documents.add(document)
        await blobs.put(document.id, b"raw")
        long_message = "parse exploded " * 100  # far beyond the truncation limit
        parser = FakeParser(error=RuntimeError(long_message))
        ingest = build_ingest(documents, chunks, blobs, parser, FakeEmbedder())

        await ingest(document.id)  # must not raise

        assert document.status is DocumentStatus.FAILED
        assert document.error is not None
        assert len(document.error) <= 500
        assert document.error.startswith("parse exploded")
        assert document.id not in chunks.stored

    async def test_embedder_failure_marks_failed(
        self,
        documents: FakeDocumentRepository,
        chunks: FakeChunkRepository,
        blobs: FakeBlobStore,
    ) -> None:
        document = make_document()
        await documents.add(document)
        await blobs.put(document.id, b"raw")
        ingest = build_ingest(
            documents, chunks, blobs, FakeParser(blocks_with_headings(2)), FakeEmbedder(fail=True)
        )
        await ingest(document.id)
        assert document.status is DocumentStatus.FAILED
        assert document.error == "embedding backend unavailable"
        assert document.id not in chunks.stored

    async def test_empty_parse_result_marks_failed(
        self,
        documents: FakeDocumentRepository,
        chunks: FakeChunkRepository,
        blobs: FakeBlobStore,
    ) -> None:
        document = make_document()
        await documents.add(document)
        await blobs.put(document.id, b"raw")
        ingest = build_ingest(documents, chunks, blobs, FakeParser(()), FakeEmbedder())
        await ingest(document.id)
        assert document.status is DocumentStatus.FAILED
        assert document.error == "document produced no chunks"

    async def test_missing_document_is_a_quiet_noop(
        self,
        documents: FakeDocumentRepository,
        chunks: FakeChunkRepository,
        blobs: FakeBlobStore,
    ) -> None:
        ingest = build_ingest(documents, chunks, blobs, FakeParser(()), FakeEmbedder())
        await ingest(uuid4())
        assert documents.status_history == []

    async def test_missing_blob_marks_failed(
        self,
        documents: FakeDocumentRepository,
        chunks: FakeChunkRepository,
        blobs: FakeBlobStore,
    ) -> None:
        document = make_document()
        await documents.add(document)
        ingest = build_ingest(
            documents, chunks, blobs, FakeParser(blocks_with_headings(1)), FakeEmbedder()
        )
        await ingest(document.id)
        assert document.status is DocumentStatus.FAILED
