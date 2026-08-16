"""Documents module — persistence ports."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from app.modules.documents.domain.entities import Chunk, Document, DocumentStatus


class DocumentRepository(Protocol):
    async def add(self, document: Document) -> None: ...

    async def get(self, document_id: UUID) -> Document | None: ...

    async def list_all(self) -> list[Document]: ...

    async def set_status(
        self,
        document_id: UUID,
        status: DocumentStatus,
        *,
        error: str | None = None,
        chunk_count: int | None = None,
    ) -> None: ...

    async def delete(self, document_id: UUID) -> None: ...


class ChunkRepository(Protocol):
    """Chunks + embeddings are replaced atomically per document (one tx)."""

    async def replace_for_document(
        self,
        document_id: UUID,
        chunks: Sequence[Chunk],
        embeddings: Sequence[tuple[float, ...]],
    ) -> None: ...

    async def preview_for_document(self, document_id: UUID, *, limit: int = 20) -> list[Chunk]: ...
