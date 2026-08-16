"""Wire schemas for the retrieval search endpoint (pydantic only at the edge)."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field

from app.modules.retrieval.domain.entities import RankedChunk


class SearchRequest(BaseModel):
    query: str = Field(description="Natural-language search query.")
    document_ids: list[UUID] | None = Field(
        default=None, description="Optional filter: search only these documents."
    )


class SearchItem(BaseModel):
    chunk_id: UUID
    document_id: UUID
    seq: int
    text: str
    filename: str
    heading_path: list[str]
    fused_score: float
    rerank_score: float | None
    dense_rank: int | None
    lexical_rank: int | None

    @classmethod
    def from_domain(cls, chunk: RankedChunk) -> SearchItem:
        return cls(
            chunk_id=chunk.chunk_id,
            document_id=chunk.document_id,
            seq=chunk.seq,
            text=chunk.text,
            filename=chunk.filename,
            heading_path=list(chunk.heading_path),
            fused_score=chunk.fused_score,
            rerank_score=chunk.rerank_score,
            dense_rank=chunk.dense_rank,
            lexical_rank=chunk.lexical_rank,
        )


class SearchResponse(BaseModel):
    items: list[SearchItem]
