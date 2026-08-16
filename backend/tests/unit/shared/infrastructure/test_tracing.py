"""Tracer adapters: no-op safety and the Langfuse SDK call mapping.

The Langfuse SDK is stubbed at the module level — these tests verify the
adapter's contract (deterministic trace-id seeding, metadata-only annotation,
span lifecycle) without network or keys.
"""

from __future__ import annotations

import sys
import types
from contextlib import contextmanager
from typing import TYPE_CHECKING

import pytest

from app.shared.domain.errors import InvalidInputError
from app.shared.infrastructure.ai.tracing import LangfuseTracer, NoopTracer

if TYPE_CHECKING:
    from collections.abc import Iterator


class _StubSpan:
    def __init__(self) -> None:
        self.updates: list[dict[str, object]] = []
        self.ended = False

    def update(self, *, metadata: dict[str, object]) -> None:
        self.updates.append(metadata)

    def end(self) -> None:
        self.ended = True


class _StubClient:
    def __init__(self, **kwargs: object) -> None:
        self.init_kwargs = kwargs
        self.observations: list[dict[str, object]] = []
        self.spans: list[_StubSpan] = []
        self.flushed = False

    def create_trace_id(self, *, seed: str | None = None) -> str:
        # Deterministic like the real SDK: same seed, same id.
        return f"traceid-{seed}"

    def start_observation(self, **kwargs: object) -> _StubSpan:
        self.observations.append(kwargs)
        span = _StubSpan()
        self.spans.append(span)
        return span

    def flush(self) -> None:
        self.flushed = True


_propagated_trace_names: list[str] = []


@contextmanager
def _stub_propagate_attributes(*, trace_name: str) -> Iterator[None]:
    _propagated_trace_names.append(trace_name)
    yield


@pytest.fixture
def stub_langfuse(monkeypatch: pytest.MonkeyPatch) -> Iterator[type[_StubClient]]:
    module = types.ModuleType("langfuse")
    module.Langfuse = _StubClient  # type: ignore[attr-defined]
    module.propagate_attributes = _stub_propagate_attributes  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "langfuse", module)
    _propagated_trace_names.clear()
    yield _StubClient


def _make_tracer() -> LangfuseTracer:
    return LangfuseTracer(public_key="pk", secret_key="sk", host="http://localhost:3001")


class TestNoopTracer:
    def test_span_yields_and_annotate_is_silent(self) -> None:
        tracer = NoopTracer()
        with tracer.span("retrieval.search", trace_id="conv-1", k=8) as span:
            span.annotate(fused=12)
        tracer.flush()


class TestLangfuseTracer:
    def test_missing_sdk_raises_actionable_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setitem(sys.modules, "langfuse", None)
        with pytest.raises(InvalidInputError, match="observability"):
            _make_tracer()

    def test_span_maps_trace_id_and_attributes(self, stub_langfuse: type[_StubClient]) -> None:
        tracer = _make_tracer()
        client = tracer._client
        with tracer.span("chat.ask", trace_id="conv-42", k=8) as span:
            span.annotate(sources=3)

        (obs,) = client.observations
        assert obs["name"] == "chat.ask"
        assert obs["as_type"] == "span"
        assert obs["trace_context"] == {"trace_id": "traceid-conv-42"}
        assert obs["metadata"] == {"k": 8}
        (stub_span,) = client.spans
        assert stub_span.updates == [{"sources": 3}]
        assert stub_span.ended

    def test_span_without_trace_id_or_attributes(self, stub_langfuse: type[_StubClient]) -> None:
        tracer = _make_tracer()
        client = tracer._client
        with tracer.span("retrieval.embed"):
            pass

        (obs,) = client.observations
        assert obs["trace_context"] is None
        assert obs["metadata"] is None

    def test_span_ends_even_when_body_raises(self, stub_langfuse: type[_StubClient]) -> None:
        tracer = _make_tracer()
        client = tracer._client
        with pytest.raises(RuntimeError), tracer.span("chat.ask"):
            raise RuntimeError("boom")
        (stub_span,) = client.spans
        assert stub_span.ended

    def test_every_span_propagates_the_roots_trace_name(
        self, stub_langfuse: type[_StubClient]
    ) -> None:
        """Langfuse names a trace by the last-ingested span, so each span must
        re-assert the first span's name or "chat.ask" becomes "retrieval.rerank"."""
        tracer = _make_tracer()
        with tracer.span("chat.ask", trace_id="conv-1"):
            pass
        with tracer.span("retrieval.rerank", trace_id="conv-1"):
            pass
        with tracer.span("retrieval.search", trace_id="conv-2"):
            pass
        assert _propagated_trace_names == ["chat.ask", "chat.ask", "retrieval.search"]

    def test_flush_delegates(self, stub_langfuse: type[_StubClient]) -> None:
        tracer = _make_tracer()
        tracer.flush()
        assert tracer._client.flushed
