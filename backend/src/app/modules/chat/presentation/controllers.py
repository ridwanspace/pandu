"""Chat HTTP controllers: conversation CRUD + the SSE answer stream.

The router is built by the composition root with fully wired use cases; no
dependency lookups happen here.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse

from app.modules.chat.application.events import (
    ChatEvent,
    DoneEvent,
    ErrorEvent,
    SourcesEvent,
    TokenEvent,
    UsageEvent,
)
from app.modules.chat.application.use_cases import (
    AskQuestion,
    GetMessages,
    ListConversations,
    StartConversation,
)
from app.modules.chat.domain.entities import Citation
from app.modules.chat.presentation.schemas import (
    AskIn,
    ConversationCreateIn,
    ConversationListOut,
    ConversationOut,
    MessageListOut,
    MessageOut,
)
from app.shared.domain.errors import InvalidInputError, NotFoundError

_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
}


def sse(event: str, data: dict[str, object]) -> str:
    """Format one Server-Sent Event frame."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _citation_payload(citation: Citation) -> dict[str, object]:
    return {
        "marker": citation.marker,
        "chunk_id": str(citation.chunk_id),
        "document_id": str(citation.document_id),
        "filename": citation.filename,
        "heading_path": list(citation.heading_path),
        "snippet": citation.snippet,
        "score": citation.score,
    }


def event_to_sse(event: ChatEvent) -> str:
    """Map one application event onto the frozen SSE wire contract."""
    match event:
        case SourcesEvent(citations=citations):
            return sse("sources", {"citations": [_citation_payload(c) for c in citations]})
        case TokenEvent(text=text):
            return sse("token", {"text": text})
        case UsageEvent(model=model, usage=usage, cost_usd=cost_usd, latency_ms=latency_ms):
            return sse(
                "usage",
                {
                    "model": model,
                    "prompt_tokens": usage.prompt_tokens,
                    "completion_tokens": usage.completion_tokens,
                    "cost_usd": str(cost_usd),
                    "latency_ms": latency_ms,
                },
            )
        case DoneEvent(message_id=message_id):
            return sse("done", {"message_id": str(message_id)})
        case ErrorEvent(detail=detail):
            return sse("error", {"detail": detail})


def build_router(
    *,
    start: StartConversation,
    list_conversations: ListConversations,
    get_messages: GetMessages,
    ask: AskQuestion,
) -> APIRouter:
    router = APIRouter(prefix="/conversations", tags=["chat"])

    @router.post("", status_code=status.HTTP_201_CREATED)
    async def create_conversation(body: ConversationCreateIn) -> ConversationOut:
        conversation = await start(body.title)
        return ConversationOut.from_domain(conversation)

    @router.get("")
    async def index() -> ConversationListOut:
        conversations = await list_conversations()
        return ConversationListOut(
            items=[ConversationOut.from_domain(conversation) for conversation in conversations]
        )

    @router.get("/{conversation_id}/messages")
    async def messages(conversation_id: UUID) -> MessageListOut:
        try:
            items = await get_messages(conversation_id)
        except NotFoundError as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        return MessageListOut(items=[MessageOut.from_domain(message) for message in items])

    @router.post("/{conversation_id}/messages")
    async def ask_question(conversation_id: UUID, body: AskIn) -> StreamingResponse:
        events = ask(conversation_id, body.question, body.document_ids)
        # Pull the first event eagerly so validation errors surface as proper
        # HTTP status codes instead of a broken event stream.
        try:
            first = await anext(events)
        except NotFoundError as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except InvalidInputError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

        async def stream() -> AsyncIterator[str]:
            yield event_to_sse(first)
            async for event in events:
                yield event_to_sse(event)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers=_SSE_HEADERS,
        )

    return router
