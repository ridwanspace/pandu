"""Chat module Postgres repositories: conversation/message round-trips, the
citations eager-load (the model is ``lazy="raise"``, so a missing selectinload
would blow up here), and Numeric(12, 6) money precision.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from app.modules.chat.domain.entities import Citation, Conversation, Message, MessageRole
from app.modules.chat.infrastructure.repositories import (
    PostgresConversationRepository,
    PostgresMessageRepository,
)
from tests.integration.support import SessionFactory


def _conversation(title: str, *, minutes_ago: int = 0) -> Conversation:
    return Conversation(
        id=uuid4(),
        title=title,
        created_at=datetime.now(UTC) - timedelta(minutes=minutes_ago),
    )


def _citation(marker: int) -> Citation:
    return Citation(
        marker=marker,
        chunk_id=uuid4(),
        document_id=uuid4(),
        filename="handbook.md",
        heading_path=("Handbook", "Security"),
        snippet=f"snippet for marker {marker}",
        score=0.5 + marker / 10,
    )


class TestConversationRepository:
    async def test_add_get_roundtrip(self, session_factory: SessionFactory) -> None:
        repo = PostgresConversationRepository(session_factory)
        conversation = _conversation("Vacation policy questions")

        await repo.add(conversation)
        loaded = await repo.get(conversation.id)

        assert loaded is not None
        assert loaded.id == conversation.id
        assert loaded.title == "Vacation policy questions"
        assert loaded.created_at == conversation.created_at

    async def test_get_missing_returns_none(self, session_factory: SessionFactory) -> None:
        repo = PostgresConversationRepository(session_factory)
        assert await repo.get(uuid4()) is None

    async def test_list_orders_newest_first(self, session_factory: SessionFactory) -> None:
        repo = PostgresConversationRepository(session_factory)
        old = _conversation("old", minutes_ago=2)
        new = _conversation("new")
        await repo.add(old)
        await repo.add(new)

        listed = await repo.list()

        assert [c.id for c in listed] == [new.id, old.id]


class TestMessageRepository:
    async def test_roundtrip_with_citations_and_cost_precision(
        self, session_factory: SessionFactory
    ) -> None:
        conversations = PostgresConversationRepository(session_factory)
        messages = PostgresMessageRepository(session_factory)
        conversation = _conversation("costs")
        await conversations.add(conversation)

        now = datetime.now(UTC)
        question = Message(
            id=uuid4(),
            conversation_id=conversation.id,
            role=MessageRole.USER,
            content="How many vacation days do we get?",
            created_at=now,
        )
        answer = Message(
            id=uuid4(),
            conversation_id=conversation.id,
            role=MessageRole.ASSISTANT,
            content="You get 25 vacation days [1][2].",
            created_at=now + timedelta(seconds=2),
            model="openai/gpt-4o-mini",
            prompt_tokens=812,
            completion_tokens=64,
            cost_usd=Decimal("0.001234"),
            latency_ms=930,
            citations=(_citation(1), _citation(2)),
        )
        await messages.add_message(question)
        await messages.add_message(answer)

        loaded = await messages.list_messages(conversation.id)

        assert [m.id for m in loaded] == [question.id, answer.id]
        assert loaded[0].role is MessageRole.USER
        assert loaded[0].citations == ()

        got = loaded[1]
        assert got.role is MessageRole.ASSISTANT
        assert got.model == "openai/gpt-4o-mini"
        assert got.prompt_tokens == 812
        assert got.completion_tokens == 64
        assert got.latency_ms == 930
        # Numeric(12, 6) must preserve the exact decimal, not a float echo.
        assert got.cost_usd == Decimal("0.001234")
        assert str(got.cost_usd) == "0.001234"

        assert [c.marker for c in got.citations] == [1, 2]
        first = got.citations[0]
        assert first.filename == "handbook.md"
        assert first.heading_path == ("Handbook", "Security")
        assert first.snippet == "snippet for marker 1"
        assert first.score == 0.6
        assert first.chunk_id == answer.citations[0].chunk_id
        assert first.document_id == answer.citations[0].document_id

    async def test_messages_are_scoped_to_their_conversation(
        self, session_factory: SessionFactory
    ) -> None:
        conversations = PostgresConversationRepository(session_factory)
        messages = PostgresMessageRepository(session_factory)
        mine = _conversation("mine")
        other = _conversation("other")
        await conversations.add(mine)
        await conversations.add(other)
        message = Message(
            id=uuid4(),
            conversation_id=mine.id,
            role=MessageRole.USER,
            content="hello",
            created_at=datetime.now(UTC),
        )
        await messages.add_message(message)

        assert [m.id for m in await messages.list_messages(mine.id)] == [message.id]
        assert await messages.list_messages(other.id) == ()

    async def test_ordering_is_chronological(self, session_factory: SessionFactory) -> None:
        conversations = PostgresConversationRepository(session_factory)
        messages = PostgresMessageRepository(session_factory)
        conversation = _conversation("ordering")
        await conversations.add(conversation)
        base = datetime.now(UTC)
        ids = []
        for offset in (2, 0, 1):  # inserted out of order on purpose
            message = Message(
                id=uuid4(),
                conversation_id=conversation.id,
                role=MessageRole.USER,
                content=f"m{offset}",
                created_at=base + timedelta(seconds=offset),
            )
            ids.append((offset, message.id))
            await messages.add_message(message)

        loaded = await messages.list_messages(conversation.id)

        expected = [message_id for _, message_id in sorted(ids)]
        assert [m.id for m in loaded] == expected
