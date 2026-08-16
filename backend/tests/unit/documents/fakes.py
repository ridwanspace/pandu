"""Hand-written in-memory fakes for the documents module ports (no I/O)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.modules.documents.domain.entities import Chunk, Document, DocumentStatus
from app.modules.documents.domain.parser import ParsedBlock, ParsedDocument
from app.shared.domain.errors import NotFoundError
from app.shared.domain.ports.embeddings import EmbeddingBatch
from app.shared.domain.values import ModelRef, TokenUsage


def make_document(**overrides: object) -> Document:
    now = datetime.now(UTC)
    defaults: dict[str, object] = {
        "id": uuid4(),
        "filename": "doc.txt",
        "content_type": "text/plain",
        "size_bytes": 42,
        "status": DocumentStatus.QUEUED,
        "created_at": now,
        "updated_at": now,
    }
    defaults.update(overrides)
    return Document(**defaults)  # type: ignore[arg-type]


class FakeDocumentRepository:
    def __init__(self) -> None:
        self.documents: dict[UUID, Document] = {}
        self.status_history: list[DocumentStatus] = []

    async def add(self, document: Document) -> None:
        self.documents[document.id] = document

    async def get(self, document_id: UUID) -> Document | None:
        return self.documents.get(document_id)

    async def list_all(self) -> list[Document]:
        return list(self.documents.values())

    async def set_status(
        self,
        document_id: UUID,
        status: DocumentStatus,
        *,
        error: str | None = None,
        chunk_count: int | None = None,
    ) -> None:
        document = self.documents[document_id]
        document.status = status
        document.error = error
        if chunk_count is not None:
            document.chunk_count = chunk_count
        self.status_history.append(status)

    async def delete(self, document_id: UUID) -> None:
        self.documents.pop(document_id, None)


class FakeChunkRepository:
    def __init__(self) -> None:
        self.stored: dict[UUID, list[Chunk]] = {}
        self.embeddings: dict[UUID, list[tuple[float, ...]]] = {}

    async def replace_for_document(
        self,
        document_id: UUID,
        chunks: Sequence[Chunk],
        embeddings: Sequence[tuple[float, ...]],
    ) -> None:
        assert len(chunks) == len(embeddings)
        self.stored[document_id] = list(chunks)
        self.embeddings[document_id] = list(embeddings)

    async def preview_for_document(self, document_id: UUID, *, limit: int = 20) -> list[Chunk]:
        return self.stored.get(document_id, [])[:limit]

    async def list_for_document(self, document_id: UUID) -> list[Chunk]:
        return list(self.stored.get(document_id, []))

    async def update_embeddings(
        self, document_id: UUID, embeddings: Sequence[tuple[float, ...]]
    ) -> None:
        assert len(embeddings) == len(self.stored.get(document_id, []))
        self.embeddings[document_id] = list(embeddings)


class FakeBlobStore:
    def __init__(self) -> None:
        self.blobs: dict[UUID, bytes] = {}

    async def put(self, document_id: UUID, content: bytes) -> None:
        self.blobs[document_id] = content

    async def get(self, document_id: UUID) -> bytes:
        if document_id not in self.blobs:
            raise NotFoundError(f"blob for document {document_id} not found")
        return self.blobs[document_id]

    async def delete(self, document_id: UUID) -> None:
        self.blobs.pop(document_id, None)


class FakeJobQueue:
    def __init__(self) -> None:
        self.enqueued: list[UUID] = []

    async def enqueue_ingest(self, document_id: UUID) -> None:
        self.enqueued.append(document_id)


class FakeEmbedder:
    """Deterministic embedder: vector encodes the text length."""

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.batch_sizes: list[int] = []

    @property
    def dimensions(self) -> int:
        return 3

    async def embed_batch(self, texts: Sequence[str]) -> EmbeddingBatch:
        if self.fail:
            raise RuntimeError("embedding backend unavailable")
        self.batch_sizes.append(len(texts))
        vectors = tuple((float(len(t)), 0.0, 1.0) for t in texts)
        return EmbeddingBatch(
            vectors=vectors,
            usage=TokenUsage(prompt_tokens=sum(len(t.split()) for t in texts)),
            model=ModelRef(provider="fake", name="embed"),
        )


class FakeParser:
    def __init__(
        self, blocks: Sequence[ParsedBlock] = (), *, error: Exception | None = None
    ) -> None:
        self.blocks = tuple(blocks)
        self.error = error

    def supports(self, content_type: str, filename: str) -> bool:
        return True

    def parse(self, content: bytes, *, filename: str, content_type: str) -> ParsedDocument:
        if self.error is not None:
            raise self.error
        return ParsedDocument(blocks=self.blocks)


def count_words(text: str) -> int:
    """Token counter fake: whitespace words."""
    return len(text.split())
