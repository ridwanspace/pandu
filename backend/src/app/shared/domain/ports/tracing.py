"""Tracing port. Langfuse implements it when configured; otherwise a no-op
tracer is wired — the platform must run fine without observability infra."""

from __future__ import annotations

from contextlib import AbstractContextManager
from typing import Protocol


class TraceSpan(Protocol):
    def annotate(self, **attributes: object) -> None:
        """Attach attributes (scores, ranks, counts — never prompt text)."""
        ...


class Tracer(Protocol):
    def span(
        self, name: str, *, trace_id: str | None = None, **attributes: object
    ) -> AbstractContextManager[TraceSpan]: ...

    def flush(self) -> None: ...
