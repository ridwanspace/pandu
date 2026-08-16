"""Tracer adapters: no-op by default, Langfuse when configured.

The platform must run without observability infrastructure, so the Langfuse
import is deferred and guarded (``observability`` extra). Span attributes carry
scores, ranks, counts, and ids — never prompt or document text.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

from app.shared.domain.errors import InvalidInputError

if TYPE_CHECKING:
    from collections.abc import Iterator

    from app.shared.domain.ports.tracing import TraceSpan


class NoopSpan:
    def annotate(self, **attributes: object) -> None:
        return None


class NoopTracer:
    @contextmanager
    def span(
        self, name: str, *, trace_id: str | None = None, **attributes: object
    ) -> Iterator[TraceSpan]:
        yield NoopSpan()

    def flush(self) -> None:
        return None


class _LangfuseSpan:
    def __init__(self, span: Any) -> None:
        self._span = span

    def annotate(self, **attributes: object) -> None:
        """Attributes become span metadata. Callers pass metrics and ids only;
        this adapter never forwards request or document content."""
        self._span.update(metadata=dict(attributes))


class LangfuseTracer:
    """Adapter for the OTel-based Langfuse SDK (v3+).

    Application trace ids are free-form strings (conversation/document ids);
    OTel requires 32-hex trace ids, so they are derived deterministically via
    ``create_trace_id(seed=...)`` — the same app id always lands in the same
    Langfuse trace.
    """

    def __init__(self, *, public_key: str, secret_key: str, host: str) -> None:
        try:
            from langfuse import Langfuse, propagate_attributes
        except ImportError as exc:
            msg = (
                "langfuse is not installed; tracing requires the 'observability' "
                "extra (uv sync --extra observability)"
            )
            raise InvalidInputError(msg) from exc
        self._client: Any = Langfuse(public_key=public_key, secret_key=secret_key, host=host)
        self._propagate: Any = propagate_attributes
        # OTel trace id -> name of the first span seen for it. Langfuse names a
        # trace by the LAST ingested span, so every span re-propagates the root
        # name ("chat.ask", not whichever retrieval step happened to flush last).
        self._trace_names: dict[str, str] = {}

    @contextmanager
    def span(
        self, name: str, *, trace_id: str | None = None, **attributes: object
    ) -> Iterator[TraceSpan]:
        trace_context = None
        trace_name = name
        if trace_id is not None:
            otel_id: str = self._client.create_trace_id(seed=trace_id)
            trace_context = {"trace_id": otel_id}
            if len(self._trace_names) > 1024:
                self._trace_names.clear()
            trace_name = self._trace_names.setdefault(otel_id, name)
        with self._propagate(trace_name=trace_name):
            span: Any = self._client.start_observation(
                name=name,
                as_type="span",
                trace_context=trace_context,
                metadata=dict(attributes) or None,
            )
        try:
            yield _LangfuseSpan(span)
        finally:
            span.end()

    def flush(self) -> None:
        self._client.flush()
