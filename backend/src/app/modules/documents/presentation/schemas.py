"""Documents module — HTTP response schemas (pydantic lives only at the edge)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.modules.documents.domain.entities import Chunk, Document


class UploadAcceptedOut(BaseModel):
    id: UUID
    filename: str
    status: str

    @classmethod
    def from_domain(cls, document: Document) -> UploadAcceptedOut:
        return cls(id=document.id, filename=document.filename, status=document.status.value)


class DocumentOut(BaseModel):
    id: UUID
    filename: str
    content_type: str
    size_bytes: int
    status: str
    error: str | None
    chunk_count: int
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_domain(cls, document: Document) -> DocumentOut:
        return cls(
            id=document.id,
            filename=document.filename,
            content_type=document.content_type,
            size_bytes=document.size_bytes,
            status=document.status.value,
            error=document.error,
            chunk_count=document.chunk_count,
            created_at=document.created_at,
            updated_at=document.updated_at,
        )


class DocumentListOut(BaseModel):
    items: list[DocumentOut]


class ChunkOut(BaseModel):
    seq: int
    text: str
    token_count: int
    heading_path: list[str]

    @classmethod
    def from_domain(cls, chunk: Chunk) -> ChunkOut:
        return cls(
            seq=chunk.seq,
            text=chunk.text,
            token_count=chunk.token_count,
            heading_path=list(chunk.heading_path),
        )


class ChunkListOut(BaseModel):
    items: list[ChunkOut]
