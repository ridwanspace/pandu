"""Documents module — domain entities."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class DocumentStatus(StrEnum):
    QUEUED = "queued"
    PARSING = "parsing"
    EMBEDDING = "embedding"
    READY = "ready"
    FAILED = "failed"


@dataclass(slots=True)
class Document:
    id: UUID
    filename: str
    content_type: str
    size_bytes: int
    status: DocumentStatus
    created_at: datetime
    updated_at: datetime
    error: str | None = None
    chunk_count: int = 0
    # Chunking parameters recorded per document for reproducibility.
    chunk_params: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Chunk:
    """One retrievable unit of a document, pre-embedding."""

    document_id: UUID
    seq: int
    text: str
    token_count: int
    heading_path: tuple[str, ...] = ()
