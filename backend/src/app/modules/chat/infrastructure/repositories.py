"""Postgres repositories for the chat module with hand-written mappers.

Each call opens its own session: the SSE stream persists messages at two
distinct points in time, so sessions must not outlive a single operation.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from app.modules.chat.domain.entities import Citation, Conversation, Message, MessageRole
from app.modules.chat.infrastructure.models import CitationModel, ConversationModel, MessageModel


def _conversation_to_domain(model: ConversationModel) -> Conversation:
    return Conversation(id=model.id, title=model.title, created_at=model.created_at)


def _citation_to_domain(model: CitationModel) -> Citation:
    return Citation(
        marker=model.marker,
        chunk_id=model.chunk_id,
        document_id=model.document_id,
        filename=model.filename,
        heading_path=tuple(model.heading_path),
        snippet=model.snippet,
        score=model.score,
    )


def _message_to_domain(model: MessageModel) -> Message:
    return Message(
        id=model.id,
        conversation_id=model.conversation_id,
        role=MessageRole(model.role),
        content=model.content,
        created_at=model.created_at,
        model=model.model,
        prompt_tokens=model.prompt_tokens,
        completion_tokens=model.completion_tokens,
        cost_usd=model.cost_usd,
        latency_ms=model.latency_ms,
        citations=tuple(_citation_to_domain(citation) for citation in model.citations),
    )


def _citation_to_model(citation: Citation, message_id: UUID) -> CitationModel:
    return CitationModel(
        message_id=message_id,
        marker=citation.marker,
        chunk_id=citation.chunk_id,
        document_id=citation.document_id,
        filename=citation.filename,
        heading_path=list(citation.heading_path),
        snippet=citation.snippet,
        score=citation.score,
    )


class PostgresConversationRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def add(self, conversation: Conversation) -> None:
        async with self._session_factory() as session, session.begin():
            session.add(
                ConversationModel(
                    id=conversation.id,
                    title=conversation.title,
                    created_at=conversation.created_at,
                )
            )

    async def get(self, conversation_id: UUID) -> Conversation | None:
        async with self._session_factory() as session:
            model = await session.get(ConversationModel, conversation_id)
            return _conversation_to_domain(model) if model is not None else None

    async def list(self) -> tuple[Conversation, ...]:
        async with self._session_factory() as session:
            result = await session.scalars(
                select(ConversationModel).order_by(ConversationModel.created_at.desc())
            )
            return tuple(_conversation_to_domain(model) for model in result)


class PostgresMessageRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def add_message(self, message: Message) -> None:
        async with self._session_factory() as session, session.begin():
            session.add(
                MessageModel(
                    id=message.id,
                    conversation_id=message.conversation_id,
                    role=message.role.value,
                    content=message.content,
                    created_at=message.created_at,
                    model=message.model,
                    prompt_tokens=message.prompt_tokens,
                    completion_tokens=message.completion_tokens,
                    cost_usd=message.cost_usd,
                    latency_ms=message.latency_ms,
                )
            )
            for citation in message.citations:
                session.add(_citation_to_model(citation, message.id))

    async def list_messages(self, conversation_id: UUID) -> tuple[Message, ...]:
        async with self._session_factory() as session:
            result = await session.scalars(
                select(MessageModel)
                .where(MessageModel.conversation_id == conversation_id)
                .options(selectinload(MessageModel.citations))
                .order_by(MessageModel.created_at, MessageModel.id)
            )
            return tuple(_message_to_domain(model) for model in result)
