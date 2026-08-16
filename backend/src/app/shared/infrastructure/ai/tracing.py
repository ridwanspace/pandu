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
    def __init__(self, *, public_key: str, secret_key: str, host: str) -> None:
        try:
            from langfuse import Langfuse
        except ImportError as exc:
            msg = (
                "langfuse is not installed; tracing requires the 'observability' "
                "extra (uv sync --extra observability)"
            )
            raise InvalidInputError(msg) from exc
        self._client: Any = Langfuse(public_key=public_key, secret_key=secret_key, host=host)

    @contextmanager
    def span(
        self, name: str, *, trace_id: str | None = None, **attributes: object
    ) -> Iterator[TraceSpan]:
        span: Any = self._client.span(
            name=name, trace_id=trace_id, metadata=dict(attributes) or None
        )
        try:
            yield _LangfuseSpan(span)
        finally:
            span.end()

    def flush(self) -> None:
        self._client.flush()
