"""Hand-written fakes implementing the AI ports (no I/O, no mocks)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.shared.domain.ports.llm import (
    CompletionRequest,
    CompletionResult,
    StreamCompleted,
    StreamDelta,
    StreamEvent,
)
from app.shared.domain.values import ModelRef, TokenUsage

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence

    from app.shared.domain.ports.cost import CostEvent


class FakeLLMProvider:
    """Succeeds with a canned result, or raises; streaming can fail after a
    configurable number of yielded events to exercise mid-stream semantics."""

    def __init__(
        self,
        *,
        model: ModelRef,
        text: str = "ok",
        usage: TokenUsage | None = None,
        error: Exception | None = None,
        fail_stream_after: int | None = None,
    ) -> None:
        self.model = model
        self._text = text
        self._usage = usage or TokenUsage(prompt_tokens=10, completion_tokens=5)
        self._error = error
        self._fail_stream_after = fail_stream_after
        self.complete_calls = 0
        self.stream_calls = 0

    async def complete(self, request: CompletionRequest) -> CompletionResult:
        self.complete_calls += 1
        if self._error is not None:
            raise self._error
        return CompletionResult(text=self._text, usage=self._usage, model=self.model)

    async def stream(self, request: CompletionRequest) -> AsyncIterator[StreamEvent]:
        """With ``error`` set, raises after ``fail_stream_after`` events
        (default 0 — i.e. before the first token)."""
        self.stream_calls += 1
        fail_after = self._fail_stream_after if self._fail_stream_after is not None else 0
        events: list[StreamEvent] = [
            *[StreamDelta(text=part) for part in self._text.split()],
            StreamCompleted(usage=self._usage, model=self.model),
        ]
        for position, event in enumerate(events):
            if self._error is not None and position >= fail_after:
                raise self._error
            yield event


class FakeCostRecorder:
    def __init__(self) -> None:
        self.events: list[CostEvent] = []

    async def record(self, event: CostEvent) -> None:
        self.events.append(event)


def make_request() -> CompletionRequest:
    from app.shared.domain.ports.llm import ChatMessage

    return CompletionRequest(messages=(ChatMessage(role="user", content="hi"),))


def openai_ref(name: str = "gpt-4o-mini") -> ModelRef:
    return ModelRef(provider="openai", name=name)


async def collect_events(iterator: AsyncIterator[StreamEvent]) -> list[StreamEvent]:
    return [event async for event in iterator]


def delta_text(events: Sequence[StreamEvent]) -> str:
    return "".join(e.text for e in events if isinstance(e, StreamDelta))
