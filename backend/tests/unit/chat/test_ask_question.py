"""AskQuestion end-to-end against in-memory fakes (no I/O, no mocks)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

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
from app.modules.chat.domain.entities import Conversation, Message, MessageRole
from app.modules.retrieval.application.dto import RetrievalQuery, RetrievedContext
from app.modules.retrieval.domain.entities import RankedChunk
from app.shared.domain.errors import InvalidInputError, NotFoundError, ProviderError
from app.shared.domain.ports.llm import (
    CompletionRequest,
    CompletionResult,
    StreamCompleted,
    StreamDelta,
    StreamEvent,
)
from app.shared.domain.values import ModelRef, TokenUsage

# ── fakes ────────────────────────────────────────────────────────────────────


class InMemoryConversationRepository:
    def __init__(self) -> None:
        self.items: dict[UUID, Conversation] = {}

    async def add(self, conversation: Conversation) -> None:
        self.items[conversation.id] = conversation

    async def get(self, conversation_id: UUID) -> Conversation | None:
        return self.items.get(conversation_id)

    async def list(self) -> tuple[Conversation, ...]:
        return tuple(self.items.values())


class InMemoryMessageRepository:
    def __init__(self) -> None:
        self.items: list[Message] = []

    async def add_message(self, message: Message) -> None:
        self.items.append(message)

    async def list_messages(self, conversation_id: UUID) -> tuple[Message, ...]:
        return tuple(m for m in self.items if m.conversation_id == conversation_id)


class FakeSpan:
    def __init__(self, annotations: dict[str, object]) -> None:
        self._annotations = annotations

    def annotate(self, **attributes: object) -> None:
        self._annotations.update(attributes)


class FakeTracer:
    def __init__(self) -> None:
        self.annotations: dict[str, object] = {}

    @contextmanager
    def span(
        self, name: str, *, trace_id: str | None = None, **attributes: object
    ) -> Iterator[FakeSpan]:
        yield FakeSpan(self.annotations)

    def flush(self) -> None:
        pass


def _chunk(seq: int, text: str) -> RankedChunk:
    return RankedChunk(
        chunk_id=uuid4(),
        document_id=uuid4(),
        seq=seq,
        text=text,
        filename=f"doc{seq}.md",
        heading_path=("Guide",),
        fused_score=0.9 - seq / 10,
        rerank_score=0.8 - seq / 10,
    )


class FakeRetrieve:
    def __init__(self, chunks: tuple[RankedChunk, ...]) -> None:
        self._chunks = chunks
        self.queries: list[RetrievalQuery] = []

    async def __call__(
        self, query: RetrievalQuery, *, trace_id: str | None = None
    ) -> RetrievedContext:
        self.queries.append(query)
        return RetrievedContext(
            chunks=self._chunks,
            candidate_count=20,
            reranker="fake",
            embed_latency_ms=1,
            search_latency_ms=2,
            rerank_latency_ms=3,
        )


class FakeStreamingLLM:
    def __init__(self, deltas: tuple[str, ...], usage: TokenUsage, model: ModelRef) -> None:
        self._deltas = deltas
        self._usage = usage
        self._model = model

    async def complete(self, request: CompletionRequest) -> CompletionResult:
        raise NotImplementedError

    async def stream(self, request: CompletionRequest) -> AsyncIterator[StreamEvent]:
        for delta in self._deltas:
            yield StreamDelta(text=delta)
        yield StreamCompleted(usage=self._usage, model=self._model)


class FailingLLM:
    async def complete(self, request: CompletionRequest) -> CompletionResult:
        raise NotImplementedError

    async def stream(self, request: CompletionRequest) -> AsyncIterator[StreamEvent]:
        yield StreamDelta(text="partial")
        raise ProviderError("boom", provider="openai", model="gpt-4o-mini", retryable=False)


# ── fixture assembly ─────────────────────────────────────────────────────────


MODEL = ModelRef(provider="openai", name="gpt-4o-mini")
USAGE = TokenUsage(prompt_tokens=120, completion_tokens=30)


def _make_ask(
    conversations: InMemoryConversationRepository,
    messages: InMemoryMessageRepository,
    llm: FakeStreamingLLM | FailingLLM,
    retrieve: FakeRetrieve,
    tracer: FakeTracer | None = None,
) -> AskQuestion:
    return AskQuestion(
        conversations=conversations,
        messages=messages,
        retrieve=retrieve,  # type: ignore[arg-type]
        llm=llm,
        tracer=tracer or FakeTracer(),
        estimate_cost=lambda model, usage: Decimal("0.000123"),
        max_question_chars=200,
    )


async def _start_conversation(conversations: InMemoryConversationRepository) -> Conversation:
    return await StartConversation(conversations=conversations)("test chat")


async def _collect(events: AsyncIterator[ChatEvent]) -> list[ChatEvent]:
    return [event async for event in events]


# ── tests ────────────────────────────────────────────────────────────────────


async def test_happy_path_event_order_and_persistence() -> None:
    conversations = InMemoryConversationRepository()
    messages = InMemoryMessageRepository()
    retrieve = FakeRetrieve((_chunk(1, "install with uv"), _chunk(2, "configure the env")))
    llm = FakeStreamingLLM(("Use uv ", "[1] to install."), USAGE, MODEL)
    conversation = await _start_conversation(conversations)
    ask = _make_ask(conversations, messages, llm, retrieve)

    events = await _collect(ask(conversation.id, "How do I install?"))

    # Order: sources -> token* -> usage -> done.
    assert isinstance(events[0], SourcesEvent)
    assert [type(e) for e in events[1:3]] == [TokenEvent, TokenEvent]
    assert isinstance(events[3], UsageEvent)
    assert isinstance(events[4], DoneEvent)
    assert len(events) == 5

    sources = events[0]
    assert [c.marker for c in sources.citations] == [1, 2]
    assert sources.citations[0].snippet == "install with uv"
    assert sources.citations[0].filename == "doc1.md"

    usage_event = events[3]
    assert usage_event.model == "openai/gpt-4o-mini"
    assert usage_event.usage == USAGE
    assert usage_event.cost_usd == Decimal("0.000123")
    assert usage_event.latency_ms >= 0

    # Persistence: user message then assistant message with only USED citations.
    persisted = await messages.list_messages(conversation.id)
    assert [m.role for m in persisted] == [MessageRole.USER, MessageRole.ASSISTANT]
    assistant = persisted[1]
    assert assistant.id == events[4].message_id
    assert assistant.content == "Use uv [1] to install."
    assert assistant.model == "openai/gpt-4o-mini"
    assert assistant.prompt_tokens == 120
    assert assistant.completion_tokens == 30
    assert assistant.cost_usd == Decimal("0.000123")
    assert [c.marker for c in assistant.citations] == [1]  # [2] was retrieved, not cited


async def test_valid_citations_are_annotated_as_fully_valid() -> None:
    conversations = InMemoryConversationRepository()
    messages = InMemoryMessageRepository()
    retrieve = FakeRetrieve((_chunk(1, "install with uv"), _chunk(2, "configure the env")))
    llm = FakeStreamingLLM(("Use uv ", "[1] to install."), USAGE, MODEL)
    conversation = await _start_conversation(conversations)
    tracer = FakeTracer()
    ask = _make_ask(conversations, messages, llm, retrieve, tracer)

    await _collect(ask(conversation.id, "How do I install?"))

    assert tracer.annotations["invalid_citation_count"] == 0
    assert tracer.annotations["citation_validity"] == 1.0


async def test_hallucinated_marker_is_annotated_and_not_persisted() -> None:
    conversations = InMemoryConversationRepository()
    messages = InMemoryMessageRepository()
    retrieve = FakeRetrieve((_chunk(1, "install with uv"),))
    llm = FakeStreamingLLM(("Use uv [1] ", "and see [9]."), USAGE, MODEL)
    conversation = await _start_conversation(conversations)
    tracer = FakeTracer()
    ask = _make_ask(conversations, messages, llm, retrieve, tracer)

    events = await _collect(ask(conversation.id, "How do I install?"))

    # Event union and ordering are unchanged: no new event type is emitted.
    assert [type(e) for e in events] == [
        SourcesEvent,
        TokenEvent,
        TokenEvent,
        UsageEvent,
        DoneEvent,
    ]
    assert tracer.annotations["invalid_citation_count"] == 1
    assert tracer.annotations["citation_validity"] == 0.5
    persisted = await messages.list_messages(conversation.id)
    assert [c.marker for c in persisted[-1].citations] == [1]


async def test_abstention_scores_as_valid() -> None:
    conversations = InMemoryConversationRepository()
    messages = InMemoryMessageRepository()
    retrieve = FakeRetrieve((_chunk(1, "unrelated"),))
    llm = FakeStreamingLLM(("The context does not cover this.",), USAGE, MODEL)
    conversation = await _start_conversation(conversations)
    tracer = FakeTracer()
    ask = _make_ask(conversations, messages, llm, retrieve, tracer)

    await _collect(ask(conversation.id, "Unanswerable?"))

    assert tracer.annotations["invalid_citation_count"] == 0
    assert tracer.annotations["citation_validity"] == 1.0
    persisted = await messages.list_messages(conversation.id)
    assert persisted[-1].citations == ()


async def test_provider_failure_annotates_error_and_no_citation_validity() -> None:
    conversations = InMemoryConversationRepository()
    messages = InMemoryMessageRepository()
    retrieve = FakeRetrieve((_chunk(1, "text"),))
    conversation = await _start_conversation(conversations)
    tracer = FakeTracer()
    ask = _make_ask(conversations, messages, FailingLLM(), retrieve, tracer)

    await _collect(ask(conversation.id, "How?"))

    assert tracer.annotations["error"] == "ProviderError"
    assert "citation_validity" not in tracer.annotations


async def test_document_ids_are_forwarded_to_retrieval() -> None:
    conversations = InMemoryConversationRepository()
    messages = InMemoryMessageRepository()
    retrieve = FakeRetrieve((_chunk(1, "text"),))
    llm = FakeStreamingLLM(("ok",), USAGE, MODEL)
    conversation = await _start_conversation(conversations)
    ask = _make_ask(conversations, messages, llm, retrieve)
    scope = (uuid4(),)

    await _collect(ask(conversation.id, "q?", scope))

    assert retrieve.queries == [RetrievalQuery(text="q?", document_ids=scope)]


async def test_without_cost_estimator_cost_is_zero() -> None:
    conversations = InMemoryConversationRepository()
    messages = InMemoryMessageRepository()
    retrieve = FakeRetrieve((_chunk(1, "text"),))
    conversation = await _start_conversation(conversations)
    ask = AskQuestion(
        conversations=conversations,
        messages=messages,
        retrieve=retrieve,  # type: ignore[arg-type]
        llm=FakeStreamingLLM(("ok",), USAGE, MODEL),
        tracer=FakeTracer(),
    )

    events = await _collect(ask(conversation.id, "How?"))

    usage_event = next(e for e in events if isinstance(e, UsageEvent))
    assert usage_event.cost_usd == Decimal("0")
    persisted = await messages.list_messages(conversation.id)
    assert persisted[-1].role is MessageRole.ASSISTANT
    assert persisted[-1].cost_usd == Decimal("0")


async def test_list_conversations_returns_started_conversations() -> None:
    conversations = InMemoryConversationRepository()
    first = await _start_conversation(conversations)
    second = await _start_conversation(conversations)

    listed = await ListConversations(conversations=conversations)()

    assert listed == (first, second)


async def test_provider_failure_yields_error_and_persists_no_assistant_message() -> None:
    conversations = InMemoryConversationRepository()
    messages = InMemoryMessageRepository()
    retrieve = FakeRetrieve((_chunk(1, "text"), _chunk(2, "more")))
    conversation = await _start_conversation(conversations)
    ask = _make_ask(conversations, messages, FailingLLM(), retrieve)

    events = await _collect(ask(conversation.id, "How?"))

    assert isinstance(events[-1], ErrorEvent)
    assert "boom" in events[-1].detail
    assert not any(isinstance(e, UsageEvent | DoneEvent) for e in events)
    persisted = await messages.list_messages(conversation.id)
    assert [m.role for m in persisted] == [MessageRole.USER]


async def test_question_too_long_raises_invalid_input() -> None:
    conversations = InMemoryConversationRepository()
    messages = InMemoryMessageRepository()
    retrieve = FakeRetrieve((_chunk(1, "text"),))
    conversation = await _start_conversation(conversations)
    ask = _make_ask(conversations, messages, FakeStreamingLLM((), USAGE, MODEL), retrieve)

    with pytest.raises(InvalidInputError):
        await _collect(ask(conversation.id, "x" * 201))
    assert messages.items == []


async def test_empty_question_raises_invalid_input() -> None:
    conversations = InMemoryConversationRepository()
    messages = InMemoryMessageRepository()
    retrieve = FakeRetrieve((_chunk(1, "text"),))
    conversation = await _start_conversation(conversations)
    ask = _make_ask(conversations, messages, FakeStreamingLLM((), USAGE, MODEL), retrieve)

    with pytest.raises(InvalidInputError):
        await _collect(ask(conversation.id, "   "))


async def test_unknown_conversation_raises_not_found() -> None:
    conversations = InMemoryConversationRepository()
    messages = InMemoryMessageRepository()
    retrieve = FakeRetrieve((_chunk(1, "text"),))
    ask = _make_ask(conversations, messages, FakeStreamingLLM((), USAGE, MODEL), retrieve)

    with pytest.raises(NotFoundError):
        await _collect(ask(uuid4(), "hello?"))


async def test_get_messages_raises_not_found_for_unknown_conversation() -> None:
    conversations = InMemoryConversationRepository()
    messages = InMemoryMessageRepository()
    get_messages = GetMessages(conversations=conversations, messages=messages)

    with pytest.raises(NotFoundError):
        await get_messages(uuid4())
