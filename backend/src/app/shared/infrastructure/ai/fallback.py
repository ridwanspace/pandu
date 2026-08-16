"""Fallback chain over LLM providers.

Providers are tried in order on *retryable* ProviderErrors; a non-retryable
error (auth, bad request) aborts immediately because it would fail identically
everywhere the same request goes. Streaming falls through only while nothing
has been yielded — once tokens reached the client the response is tainted and
the error must propagate.

Whether a call was served by a non-primary provider is exposed through a
task-local flag (contextvar) so the metering decorator can stamp
``fallback_used`` on the CostEvent without widening the port types.
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import TYPE_CHECKING

import structlog

from app.shared.domain.errors import AllProvidersFailedError, InvalidInputError, ProviderError
from app.shared.domain.ports.llm import CompletionRequest, CompletionResult, StreamEvent

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence

    from app.shared.domain.ports.llm import LLMProvider
    from app.shared.domain.values import ModelRef

_log = structlog.get_logger(__name__)

_fallback_used: ContextVar[bool] = ContextVar("pandu_ai_fallback_used", default=False)


def reset_fallback_used() -> None:
    """Clear the per-call flag; called at the start of every metered call so a
    previous call in the same task cannot leak its flag forward."""
    _fallback_used.set(False)


def was_fallback_used() -> bool:
    return _fallback_used.get()


class FallbackLLMProvider:
    """Implements LLMProvider over an ordered chain of (ModelRef, provider)."""

    def __init__(self, providers: Sequence[tuple[ModelRef, LLMProvider]]) -> None:
        if not providers:
            msg = "fallback chain needs at least one provider"
            raise InvalidInputError(msg)
        self._providers: tuple[tuple[ModelRef, LLMProvider], ...] = tuple(providers)

    async def complete(self, request: CompletionRequest) -> CompletionResult:
        reset_fallback_used()
        errors: list[ProviderError] = []
        for position, (ref, provider) in enumerate(self._providers):
            try:
                result = await provider.complete(request)
            except ProviderError as exc:
                if not exc.retryable:
                    raise
                errors.append(exc)
                _log.warning(
                    "provider failed; trying next in chain",
                    provider=ref.provider,
                    model=ref.name,
                    position=position,
                    remaining=len(self._providers) - position - 1,
                )
                continue
            if position > 0:
                _fallback_used.set(True)
            return result
        raise AllProvidersFailedError(errors)

    async def stream(self, request: CompletionRequest) -> AsyncIterator[StreamEvent]:
        reset_fallback_used()
        errors: list[ProviderError] = []
        for position, (ref, provider) in enumerate(self._providers):
            yielded_any = False
            try:
                async for event in provider.stream(request):
                    if not yielded_any:
                        yielded_any = True
                        if position > 0:
                            _fallback_used.set(True)
                    yield event
                return
            except ProviderError as exc:
                if yielded_any or not exc.retryable:
                    # Mid-stream failure: the consumer already received tokens,
                    # so silently restarting on another provider would duplicate
                    # output. Surface the error instead.
                    raise
                errors.append(exc)
                _log.warning(
                    "provider failed before first token; trying next in chain",
                    provider=ref.provider,
                    model=ref.name,
                    position=position,
                    remaining=len(self._providers) - position - 1,
                )
        raise AllProvidersFailedError(errors)
