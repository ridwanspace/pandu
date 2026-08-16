"""Pydantic edge schemas for the chat HTTP API."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.modules.chat.domain.entities import Citation, Conversation, Message


class ConversationCreateIn(BaseModel):
    title: str | None = None


class ConversationOut(BaseModel):
    id: UUID
    title: str
    created_at: datetime

    @classmethod
    def from_domain(cls, conversation: Conversation) -> ConversationOut:
        return cls(
            id=conversation.id,
            title=conversation.title,
            created_at=conversation.created_at,
        )


class ConversationListOut(BaseModel):
    items: list[ConversationOut]


class CitationOut(BaseModel):
    marker: int
    chunk_id: UUID
    document_id: UUID
    filename: str
    heading_path: list[str]
    snippet: str
    score: float

    @classmethod
    def from_domain(cls, citation: Citation) -> CitationOut:
        return cls(
            marker=citation.marker,
            chunk_id=citation.chunk_id,
            document_id=citation.document_id,
            filename=citation.filename,
            heading_path=list(citation.heading_path),
            snippet=citation.snippet,
            score=citation.score,
        )


class MessageOut(BaseModel):
    id: UUID
    role: str
    content: str
    created_at: datetime
    model: str | None
    prompt_tokens: int
    completion_tokens: int
    cost_usd: str
    latency_ms: int
    citations: list[CitationOut]

    @classmethod
    def from_domain(cls, message: Message) -> MessageOut:
        return cls(
            id=message.id,
            role=message.role.value,
            content=message.content,
            created_at=message.created_at,
            model=message.model,
            prompt_tokens=message.prompt_tokens,
            completion_tokens=message.completion_tokens,
            cost_usd=str(message.cost_usd),
            latency_ms=message.latency_ms,
            citations=[CitationOut.from_domain(citation) for citation in message.citations],
        )


class MessageListOut(BaseModel):
    items: list[MessageOut]


class AskIn(BaseModel):
    question: str = Field(min_length=1)
    document_ids: list[UUID] | None = None
