"""Chat module — domain entities."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID


class MessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


@dataclass(slots=True)
class Conversation:
    id: UUID
    title: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class Citation:
    """A numbered source marker ([1], [2], ...) grounding part of an answer."""

    marker: int
    chunk_id: UUID
    document_id: UUID
    filename: str
    heading_path: tuple[str, ...]
    snippet: str
    score: float


@dataclass(slots=True)
class Message:
    id: UUID
    conversation_id: UUID
    role: MessageRole
    content: str
    created_at: datetime
    model: str | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: Decimal = Decimal("0")
    latency_ms: int = 0
    citations: tuple[Citation, ...] = field(default=())
