"""SQLAlchemy models for the chat module (conversations, messages, citations)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Float, ForeignKey, Integer, Numeric, String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.shared.infrastructure.db.base import Base


class ConversationModel(Base):
    __tablename__ = "conversations"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MessageModel(Base):
    __tablename__ = "messages"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False, default=Decimal("0"))
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    citations: Mapped[list[CitationModel]] = relationship(
        cascade="all, delete-orphan",
        order_by="CitationModel.marker",
        lazy="raise",
    )


class CitationModel(Base):
    __tablename__ = "citations"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    message_id: Mapped[UUID] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), nullable=False, index=True
    )
    marker: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    document_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    heading_path: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    snippet: Mapped[str] = mapped_column(Text, nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
