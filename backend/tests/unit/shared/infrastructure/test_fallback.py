"""Fallback chain: ordering, retryable vs final errors, streaming semantics."""

from __future__ import annotations

import pytest

from app.shared.domain.errors import AllProvidersFailedError, InvalidInputError, ProviderError
from app.shared.domain.ports.llm import StreamCompleted
from app.shared.domain.values import ModelRef
from app.shared.infrastructure.ai.fallback import FallbackLLMProvider, was_fallback_used
from tests.unit.shared.infrastructure.fakes import (
    FakeLLMProvider,
    collect_events,
    delta_text,
    make_request,
)

PRIMARY = ModelRef(provider="openai", name="gpt-4o-mini")
SECONDARY = ModelRef(provider="gemini", name="gemini-2.0-flash")


def _retryable(model: ModelRef) -> ProviderError:
    return ProviderError("boom", provider=model.provider, model=model.name, retryable=True)


def _final(model: ModelRef) -> ProviderError:
    return ProviderError("denied", provider=model.provider, model=model.name, retryable=False)


class TestComplete:
    async def test_primary_success_uses_primary_only(self) -> None:
        primary = FakeLLMProvider(model=PRIMARY, text="from-primary")
        secondary = FakeLLMProvider(model=SECONDARY, text="from-secondary")
        chain = FallbackLLMProvider([(PRIMARY, primary), (SECONDARY, secondary)])

        result = await chain.complete(make_request())

        assert result.text == "from-primary"
        assert secondary.complete_calls == 0
        assert was_fallback_used() is False

    async def test_retryable_failure_falls_through(self) -> None:
        primary = FakeLLMProvider(model=PRIMARY, error=_retryable(PRIMARY))
        secondary = FakeLLMProvider(model=SECONDARY, text="from-secondary")
        chain = FallbackLLMProvider([(PRIMARY, primary), (SECONDARY, secondary)])

        result = await chain.complete(make_request())

        assert result.text == "from-secondary"
        assert result.model == SECONDARY
        assert was_fallback_used() is True

    async def test_non_retryable_failure_aborts_chain(self) -> None:
        primary = FakeLLMProvider(model=PRIMARY, error=_final(PRIMARY))
        secondary = FakeLLMProvider(model=SECONDARY)
        chain = FallbackLLMProvider([(PRIMARY, primary), (SECONDARY, secondary)])

        with pytest.raises(ProviderError) as exc_info:
            await chain.complete(make_request())

        assert exc_info.value.retryable is False
        assert secondary.complete_calls == 0

    async def test_all_failed_collects_every_error(self) -> None:
        primary = FakeLLMProvider(model=PRIMARY, error=_retryable(PRIMARY))
        secondary = FakeLLMProvider(model=SECONDARY, error=_retryable(SECONDARY))
        chain = FallbackLLMProvider([(PRIMARY, primary), (SECONDARY, secondary)])

        with pytest.raises(AllProvidersFailedError) as exc_info:
            await chain.complete(make_request())

        assert [e.provider for e in exc_info.value.errors] == ["openai", "gemini"]

    def test_empty_chain_rejected(self) -> None:
        with pytest.raises(InvalidInputError):
            FallbackLLMProvider([])

    async def test_flag_resets_between_calls(self) -> None:
        failing = FakeLLMProvider(model=PRIMARY, error=_retryable(PRIMARY))
        ok = FakeLLMProvider(model=SECONDARY)
        chain = FallbackLLMProvider([(PRIMARY, failing), (SECONDARY, ok)])
        await chain.complete(make_request())
        assert was_fallback_used() is True

        healthy = FallbackLLMProvider([(PRIMARY, FakeLLMProvider(model=PRIMARY))])
        await healthy.complete(make_request())
        assert was_fallback_used() is False


class TestStream:
    async def test_pre_token_failure_falls_through(self) -> None:
        primary = FakeLLMProvider(model=PRIMARY, error=_retryable(PRIMARY))
        secondary = FakeLLMProvider(model=SECONDARY, text="hello world")
        chain = FallbackLLMProvider([(PRIMARY, primary), (SECONDARY, secondary)])

        events = await collect_events(chain.stream(make_request()))

        assert delta_text(events) == "helloworld"
        assert isinstance(events[-1], StreamCompleted)
        assert events[-1].model == SECONDARY
        assert was_fallback_used() is True

    async def test_mid_stream_failure_propagates(self) -> None:
        primary = FakeLLMProvider(
            model=PRIMARY, text="a b c", error=_retryable(PRIMARY), fail_stream_after=2
        )
        secondary = FakeLLMProvider(model=SECONDARY, text="never")
        chain = FallbackLLMProvider([(PRIMARY, primary), (SECONDARY, secondary)])

        received = []
        with pytest.raises(ProviderError):
            async for event in chain.stream(make_request()):
                received.append(event)

        assert delta_text(received) == "ab"
        assert secondary.stream_calls == 0

    async def test_pre_token_non_retryable_propagates(self) -> None:
        primary = FakeLLMProvider(model=PRIMARY, error=_final(PRIMARY))
        secondary = FakeLLMProvider(model=SECONDARY)
        chain = FallbackLLMProvider([(PRIMARY, primary), (SECONDARY, secondary)])

        with pytest.raises(ProviderError) as exc_info:
            await collect_events(chain.stream(make_request()))

        assert exc_info.value.retryable is False
        assert secondary.stream_calls == 0

    async def test_all_streams_failed(self) -> None:
        chain = FallbackLLMProvider(
            [
                (PRIMARY, FakeLLMProvider(model=PRIMARY, error=_retryable(PRIMARY))),
                (SECONDARY, FakeLLMProvider(model=SECONDARY, error=_retryable(SECONDARY))),
            ]
        )
        with pytest.raises(AllProvidersFailedError) as exc_info:
            await collect_events(chain.stream(make_request()))
        assert len(exc_info.value.errors) == 2

    async def test_primary_stream_success_no_fallback_flag(self) -> None:
        chain = FallbackLLMProvider(
            [
                (PRIMARY, FakeLLMProvider(model=PRIMARY, text="fine")),
                (SECONDARY, FakeLLMProvider(model=SECONDARY)),
            ]
        )
        events = await collect_events(chain.stream(make_request()))
        assert delta_text(events) == "fine"
        assert was_fallback_used() is False
