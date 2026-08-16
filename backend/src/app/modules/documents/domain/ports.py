"""Documents module — ingestion side-effect ports.

Persistence ports live in ``repositories.py``; these cover the job queue and
raw-upload blob storage. Uploads travel to the worker through the database
(``document_blobs``) so no shared volume is required.
"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from app.modules.documents.domain.chunking import TokenCounter

__all__ = ["BlobStore", "IngestJobQueue", "TokenCounter"]


class IngestJobQueue(Protocol):
    async def enqueue_ingest(self, document_id: UUID) -> None: ...


class BlobStore(Protocol):
    """Raw upload payload storage, keyed by document id."""

    async def put(self, document_id: UUID, content: bytes) -> None: ...

    async def get(self, document_id: UUID) -> bytes:
        """Return the stored payload; raises ``NotFoundError`` when absent."""
        ...

    async def delete(self, document_id: UUID) -> None: ...
