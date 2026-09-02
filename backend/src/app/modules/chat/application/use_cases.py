"""Chat use cases: conversation CRUD and the streaming RAG orchestration."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from app.modules.chat.application.events import (
    ChatEvent,
    CostEstimator,
    DoneEvent,
    ErrorEvent,
    SourcesEvent,
    TokenEvent,
    UsageEvent,
)
from app.modules.chat.domain.citations import validate_citations
from app.modules.chat.domain.entities import Citation, Conversation, Message, MessageRole
from app.modules.chat.domain.prompting import (
    PromptContext,
    build_grounded_prompt,
    truncate_contexts,
)
from app.modules.chat.domain.repositories import ConversationRepository, MessageRepository
from app.modules.retrieval.application.dto import RetrievalQuery
from app.shared.domain.errors import (
    AllProvidersFailedError,
    InvalidInputError,
    NotFoundError,
    ProviderError,
)
from app.shared.domain.ports.llm import (
    CompletionRequest,
    LLMProvider,
    StreamCompleted,
    StreamDelta,
)
from app.shared.domain.ports.tracing import Tracer
from app.shared.domain.values import TokenUsage

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence

    from app.modules.retrieval.application.use_cases import RetrieveContext

_DEFAULT_TITLE = "New conversation"
_SNIPPET_CHARS = 240
_CONTEXT_CHAR_BUDGET = 12_000


class StartConversation:
    def __init__(self, *, conversations: ConversationRepository) -> None:
        self._conversations = conversations

    async def __call__(self, title: str | None = None) -> Conversation:
        conversation = Conversation(
            id=uuid4(),
            title=(title or "").strip() or _DEFAULT_TITLE,
            created_at=datetime.now(UTC),
        )
        await self._conversations.add(conversation)
        return conversation


class ListConversations:
    def __init__(self, *, conversations: ConversationRepository) -> None:
        self._conversations = conversations

    async def __call__(self) -> tuple[Conversation, ...]:
        return await self._conversations.list()


class GetMessages:
    def __init__(
        self,
        *,
        conversations: ConversationRepository,
        messages: MessageRepository,
    ) -> None:
        self._conversations = conversations
        self._messages = messages

    async def __call__(self, conversation_id: UUID) -> tuple[Message, ...]:
        if await self._conversations.get(conversation_id) is None:
            msg = f"conversation {conversation_id} not found"
            raise NotFoundError(msg)
        return await self._messages.list_messages(conversation_id)


def _snippet(text: str) -> str:
    return text[:_SNIPPET_CHARS]


class AskQuestion:
    """Orchestrates one RAG turn: retrieve, ground, stream, persist.

    Yields the event union in strict order sources -> token* -> usage -> done;
    on provider failure it yields a single error event instead and persists no
    assistant message. Cost is estimated only when a CostEstimator is injected
    (metering of raw vendor calls happens in the adapter layer, not here).
    """

    def __init__(
        self,
        *,
        conversations: ConversationRepository,
        messages: MessageRepository,
        retrieve: RetrieveContext,
        llm: LLMProvider,
        tracer: Tracer,
        estimate_cost: CostEstimator | None = None,
        max_question_chars: int = 4_000,
    ) -> None:
        self._conversations = conversations
        self._messages = messages
        self._retrieve = retrieve
        self._llm = llm
        self._tracer = tracer
        self._estimate_cost = estimate_cost
        self._max_question_chars = max_question_chars

    async def __call__(
        self,
        conversation_id: UUID,
        question: str,
        document_ids: Sequence[UUID] | None = None,
    ) -> AsyncIterator[ChatEvent]:
        question = question.strip()
        if not question:
            msg = "question must not be empty"
            raise InvalidInputError(msg)
        if len(question) > self._max_question_chars:
            msg = f"question exceeds {self._max_question_chars} characters"
            raise InvalidInputError(msg)
        if await self._conversations.get(conversation_id) is None:
            msg = f"conversation {conversation_id} not found"
            raise NotFoundError(msg)

        message_id = uuid4()
        trace_id = f"{conversation_id}/{message_id}"

        await self._messages.add_message(
            Message(
                id=uuid4(),
                conversation_id=conversation_id,
                role=MessageRole.USER,
                content=question,
                created_at=datetime.now(UTC),
            )
        )

        with self._tracer.span("chat.ask", trace_id=trace_id) as span:
            context = await self._retrieve(
                RetrievalQuery(
                    text=question,
                    document_ids=tuple(document_ids) if document_ids else None,
                ),
                trace_id=trace_id,
            )
            cited: list[Citation] = []
            for index, chunk in enumerate(context.chunks, start=1):
                score = chunk.rerank_score if chunk.rerank_score is not None else chunk.fused_score
                cited.append(
                    Citation(
                        marker=index,
                        chunk_id=chunk.chunk_id,
                        document_id=chunk.document_id,
                        filename=chunk.filename,
                        heading_path=chunk.heading_path,
                        snippet=_snippet(chunk.text),
                        score=score,
                    )
                )
            citations = tuple(cited)
            yield SourcesEvent(citations=citations)

            prompt_contexts = truncate_contexts(
                tuple(
                    PromptContext(
                        marker=index,
                        filename=chunk.filename,
                        heading_path=chunk.heading_path,
                        text=chunk.text,
                    )
                    for index, chunk in enumerate(context.chunks, start=1)
                ),
                max_chars=_CONTEXT_CHAR_BUDGET,
            )
            prompt = build_grounded_prompt(question, prompt_contexts)

            parts: list[str] = []
            completed: StreamCompleted | None = None
            started = time.monotonic()
            try:
                async for event in self._llm.stream(CompletionRequest(messages=prompt)):
                    if isinstance(event, StreamDelta):
                        parts.append(event.text)
                        yield TokenEvent(text=event.text)
                    else:
                        completed = event
            except (ProviderError, AllProvidersFailedError) as exc:
                span.annotate(error=type(exc).__name__)
                yield ErrorEvent(detail=str(exc))
                return
            latency_ms = int((time.monotonic() - started) * 1000)

            answer = "".join(parts)
            usage = completed.usage if completed is not None else TokenUsage()
            model = str(completed.model) if completed is not None else "unknown"
            cost_usd = Decimal("0")
            if self._estimate_cost is not None and completed is not None:
                cost_usd = self._estimate_cost(completed.model, usage)

            # Assert grounding rather than silently dropping bad markers: the
            # counts land on the trace so hallucinated citations are measurable.
            report = validate_citations(citations, answer)

            await self._messages.add_message(
                Message(
                    id=message_id,
                    conversation_id=conversation_id,
                    role=MessageRole.ASSISTANT,
                    content=answer,
                    created_at=datetime.now(UTC),
                    model=model,
                    prompt_tokens=usage.prompt_tokens,
                    completion_tokens=usage.completion_tokens,
                    cost_usd=cost_usd,
                    latency_ms=latency_ms,
                    citations=report.cited,
                )
            )
            span.annotate(
                retrieved=len(citations),
                prompt_tokens=usage.prompt_tokens,
                completion_tokens=usage.completion_tokens,
                latency_ms=latency_ms,
                # Counts only — answer and prompt text never reach the tracer.
                invalid_citation_count=len(report.invalid_markers),
                citation_validity=report.validity,
            )
            yield UsageEvent(model=model, usage=usage, cost_usd=cost_usd, latency_ms=latency_ms)
            yield DoneEvent(message_id=message_id)
