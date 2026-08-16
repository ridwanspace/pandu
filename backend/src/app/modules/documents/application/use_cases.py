"""Documents module — application use cases.

Constructor-injected ports only; no framework imports. Log lines carry counts
and ids, never document text (see logging policy in the architecture review).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

import structlog

from app.modules.documents.domain.chunking import TokenCounter, chunk_blocks
from app.modules.documents.domain.entities import Chunk, Document, DocumentStatus
from app.modules.documents.domain.parser import DocumentParser
from app.modules.documents.domain.ports import BlobStore, IngestJobQueue
from app.modules.documents.domain.repositories import ChunkRepository, DocumentRepository
from app.shared.domain.errors import InvalidInputError, NotFoundError
from app.shared.domain.ports.embeddings import EmbeddingProvider

logger = structlog.get_logger(__name__)

ALLOWED_CONTENT_TYPES = frozenset({"application/pdf", "text/plain", "text/markdown"})

_ERROR_MAX_CHARS = 500


class UploadDocument:
    """Accept an upload: validate, persist QUEUED, store the blob, enqueue."""

    def __init__(
        self,
        *,
        documents: DocumentRepository,
        blobs: BlobStore,
        jobs: IngestJobQueue,
        max_upload_bytes: int,
        chunk_max_tokens: int,
        chunk_overlap_tokens: int,
    ) -> None:
        self._documents = documents
        self._blobs = blobs
        self._jobs = jobs
        self._max_upload_bytes = max_upload_bytes
        self._chunk_max_tokens = chunk_max_tokens
        self._chunk_overlap_tokens = chunk_overlap_tokens

    async def __call__(self, *, filename: str, content_type: str, content: bytes) -> Document:
        if not filename.strip():
            raise InvalidInputError("filename must not be empty")
        if not content:
            raise InvalidInputError("uploaded file is empty")
        if len(content) > self._max_upload_bytes:
            msg = f"file exceeds the {self._max_upload_bytes} byte upload limit"
            raise InvalidInputError(msg)
        if content_type not in ALLOWED_CONTENT_TYPES:
            allowed = ", ".join(sorted(ALLOWED_CONTENT_TYPES))
            raise InvalidInputError(
                f"unsupported content type {content_type!r}; expected {allowed}"
            )

        now = datetime.now(UTC)
        document = Document(
            id=uuid4(),
            filename=filename,
            content_type=content_type,
            size_bytes=len(content),
            status=DocumentStatus.QUEUED,
            created_at=now,
            updated_at=now,
            # Recorded per document so a chunk set is reproducible later even
            # if the global settings change.
            chunk_params={
                "max_tokens": self._chunk_max_tokens,
                "overlap_tokens": self._chunk_overlap_tokens,
            },
        )
        await self._documents.add(document)
        await self._blobs.put(document.id, content)
        await self._jobs.enqueue_ingest(document.id)
        logger.info(
            "document_upload_accepted",
            document_id=str(document.id),
            size_bytes=document.size_bytes,
        )
        return document


class ListDocuments:
    def __init__(self, *, documents: DocumentRepository) -> None:
        self._documents = documents

    async def __call__(self) -> list[Document]:
        return await self._documents.list_all()


class GetDocument:
    def __init__(self, *, documents: DocumentRepository) -> None:
        self._documents = documents

    async def __call__(self, document_id: UUID) -> Document:
        document = await self._documents.get(document_id)
        if document is None:
            raise NotFoundError(f"document {document_id} not found")
        return document


class DeleteDocument:
    """Remove a document, its blob, and (via FK cascade) its chunks."""

    def __init__(self, *, documents: DocumentRepository, blobs: BlobStore) -> None:
        self._documents = documents
        self._blobs = blobs

    async def __call__(self, document_id: UUID) -> None:
        document = await self._documents.get(document_id)
        if document is None:
            raise NotFoundError(f"document {document_id} not found")
        await self._blobs.delete(document_id)
        await self._documents.delete(document_id)
        logger.info("document_deleted", document_id=str(document_id))


class PreviewChunks:
    def __init__(self, *, documents: DocumentRepository, chunks: ChunkRepository) -> None:
        self._documents = documents
        self._chunks = chunks

    async def __call__(self, document_id: UUID, *, limit: int = 20) -> list[Chunk]:
        document = await self._documents.get(document_id)
        if document is None:
            raise NotFoundError(f"document {document_id} not found")
        return await self._chunks.preview_for_document(document_id, limit=limit)


class IngestDocument:
    """Worker-side pipeline: parse -> chunk -> embed -> replace atomically.

    Any failure marks the document FAILED with a truncated reason and is
    swallowed — the job queue must not retry a poisoned document forever.
    """

    def __init__(
        self,
        *,
        documents: DocumentRepository,
        chunks: ChunkRepository,
        blobs: BlobStore,
        parser: DocumentParser,
        embedder: EmbeddingProvider,
        count_tokens: TokenCounter,
        chunk_max_tokens: int,
        chunk_overlap_tokens: int,
        embed_batch_size: int,
    ) -> None:
        self._documents = documents
        self._chunks = chunks
        self._blobs = blobs
        self._parser = parser
        self._embedder = embedder
        self._count_tokens = count_tokens
        self._chunk_max_tokens = chunk_max_tokens
        self._chunk_overlap_tokens = chunk_overlap_tokens
        self._embed_batch_size = embed_batch_size

    async def __call__(self, document_id: UUID) -> None:
        document = await self._documents.get(document_id)
        if document is None:
            logger.warning("ingest_document_missing", document_id=str(document_id))
            return
        try:
            await self._ingest(document)
        except Exception as exc:
            error = str(exc)[:_ERROR_MAX_CHARS] or type(exc).__name__
            await self._documents.set_status(document_id, DocumentStatus.FAILED, error=error)
            logger.error(
                "document_ingest_failed",
                document_id=str(document_id),
                error_type=type(exc).__name__,
            )

    async def _ingest(self, document: Document) -> None:
        await self._documents.set_status(document.id, DocumentStatus.PARSING)
        content = await self._blobs.get(document.id)
        # Parsing is synchronous CPU-bound work; keep the event loop free.
        parsed = await asyncio.to_thread(
            self._parser.parse,
            content,
            filename=document.filename,
            content_type=document.content_type,
        )
        drafts = chunk_blocks(
            parsed.blocks,
            max_tokens=self._chunk_max_tokens,
            overlap_tokens=self._chunk_overlap_tokens,
            count_tokens=self._count_tokens,
        )
        if not drafts:
            raise InvalidInputError("document produced no chunks")

        await self._documents.set_status(document.id, DocumentStatus.EMBEDDING)
        vectors: list[tuple[float, ...]] = []
        for start in range(0, len(drafts), self._embed_batch_size):
            batch = drafts[start : start + self._embed_batch_size]
            result = await self._embedder.embed_batch([draft.text for draft in batch])
            vectors.extend(result.vectors)

        chunks = [
            Chunk(
                document_id=document.id,
                seq=seq,
                text=draft.text,
                token_count=draft.token_count,
                heading_path=draft.heading_path,
            )
            for seq, draft in enumerate(drafts)
        ]
        await self._chunks.replace_for_document(document.id, chunks, vectors)
        await self._documents.set_status(document.id, DocumentStatus.READY, chunk_count=len(chunks))
        logger.info(
            "document_ingested",
            document_id=str(document.id),
            chunk_count=len(chunks),
        )


@dataclass(frozen=True, slots=True)
class ReembedReport:
    """Outcome of an embedding-model migration pass."""

    model: str
    documents: int
    chunks: int
    skipped: int


class ReembedDocuments:
    """Re-embed stored chunk text with the currently configured embedding
    provider — no re-parse, no re-chunk (chunk text lives in Postgres).

    This is the cheap path for switching embedding models (e.g. the offline
    ``hash/ngram`` bootstrap embedder -> a semantic API model): parsing a large
    PDF costs tens of CPU-minutes, embedding the same chunks costs one API
    call per batch. Only READY documents are touched; queries embed with the
    same env-configured model, so run this once right after changing
    ``AI_EMBED_MODEL`` to keep the vector space consistent.
    """

    def __init__(
        self,
        *,
        documents: DocumentRepository,
        chunks: ChunkRepository,
        embedder: EmbeddingProvider,
        embed_batch_size: int,
    ) -> None:
        self._documents = documents
        self._chunks = chunks
        self._embedder = embedder
        self._embed_batch_size = embed_batch_size

    async def __call__(self, document_id: UUID | None = None) -> ReembedReport:
        if document_id is not None:
            document = await self._documents.get(document_id)
            if document is None:
                msg = f"document {document_id} not found"
                raise NotFoundError(msg)
            candidates = [document]
        else:
            candidates = await self._documents.list_all()

        model = ""
        documents_done = 0
        chunks_done = 0
        skipped = 0
        for document in candidates:
            if document.status is not DocumentStatus.READY:
                skipped += 1
                continue
            chunks = await self._chunks.list_for_document(document.id)
            if not chunks:
                skipped += 1
                continue
            vectors: list[tuple[float, ...]] = []
            for start in range(0, len(chunks), self._embed_batch_size):
                batch = chunks[start : start + self._embed_batch_size]
                result = await self._embedder.embed_batch([chunk.text for chunk in batch])
                vectors.extend(result.vectors)
                model = str(result.model)
            await self._chunks.update_embeddings(document.id, vectors)
            documents_done += 1
            chunks_done += len(chunks)
            logger.info(
                "document_reembedded",
                document_id=str(document.id),
                chunk_count=len(chunks),
            )
        return ReembedReport(
            model=model, documents=documents_done, chunks=chunks_done, skipped=skipped
        )
