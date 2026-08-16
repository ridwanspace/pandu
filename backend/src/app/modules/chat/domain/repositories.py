"""Persistence ports for the chat module. Implemented in infrastructure/."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from app.modules.chat.domain.entities import Conversation, Message


class ConversationRepository(Protocol):
    async def add(self, conversation: Conversation) -> None: ...

    async def get(self, conversation_id: UUID) -> Conversation | None: ...

    async def list(self) -> tuple[Conversation, ...]: ...


class MessageRepository(Protocol):
    async def add_message(self, message: Message) -> None: ...

    async def list_messages(self, conversation_id: UUID) -> tuple[Message, ...]: ...
