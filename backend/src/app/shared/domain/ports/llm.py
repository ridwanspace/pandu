"""LLM provider port: non-streaming completion + token streaming."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Literal, Protocol

from app.shared.domain.values import ModelRef, TokenUsage

Role = Literal["system", "user", "assistant"]


@dataclass(frozen=True, slots=True)
class ChatMessage:
    role: Role
    content: str


@dataclass(frozen=True, slots=True)
class CompletionRequest:
    messages: tuple[ChatMessage, ...]
    temperature: float = 0.2
    max_output_tokens: int = 1024
    # Free-form metadata forwarded to tracing (never to the vendor).
    tags: tuple[str, ...] = field(default=())


@dataclass(frozen=True, slots=True)
class CompletionResult:
    text: str
    usage: TokenUsage
    model: ModelRef


@dataclass(frozen=True, slots=True)
class StreamDelta:
    """One incremental chunk of generated text."""

    text: str


@dataclass(frozen=True, slots=True)
class StreamCompleted:
    """Terminal stream event carrying final usage; emitted exactly once."""

    usage: TokenUsage
    model: ModelRef


StreamEvent = StreamDelta | StreamCompleted


class LLMProvider(Protocol):
    """Chat-completion port. Implementations must translate vendor errors to
    :class:`app.shared.domain.errors.ProviderError`."""

    async def complete(self, request: CompletionRequest) -> CompletionResult: ...

    def stream(self, request: CompletionRequest) -> AsyncIterator[StreamEvent]: ...
