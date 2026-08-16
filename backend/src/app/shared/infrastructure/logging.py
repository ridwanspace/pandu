"""structlog configuration and request-id propagation.

JSON renderer for machines (prod), console renderer for humans (dev). Every
log line carries the request id when one is bound. Log values are counts, ids,
and durations — prompt text, document text, and API keys never appear.
"""

from __future__ import annotations

import logging
from contextvars import ContextVar
from typing import TYPE_CHECKING
from uuid import uuid4

import structlog

if TYPE_CHECKING:
    from structlog.typing import EventDict, Processor, WrappedLogger

_request_id_var: ContextVar[str | None] = ContextVar("pandu_request_id", default=None)


def bind_request_id(request_id: str | None = None) -> str:
    """Bind (or generate) the request id for the current task context and
    return it, so middleware can echo it in an X-Request-ID header."""
    value = request_id or uuid4().hex
    _request_id_var.set(value)
    return value


def get_request_id() -> str | None:
    return _request_id_var.get()


def clear_request_id() -> None:
    _request_id_var.set(None)


def _add_request_id(logger: WrappedLogger, method_name: str, event_dict: EventDict) -> EventDict:
    request_id = _request_id_var.get()
    if request_id is not None:
        event_dict["request_id"] = request_id
    return event_dict


def configure_logging(level: str = "INFO", *, json_output: bool = False) -> None:
    """Configure structlog once at startup (bootstrap and the arq worker)."""
    level_number = logging.getLevelNamesMapping().get(level.upper(), logging.INFO)
    renderer: Processor = (
        structlog.processors.JSONRenderer()
        if json_output
        else structlog.dev.ConsoleRenderer(colors=True)
    )
    processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        _add_request_id,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        renderer,
    ]
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(level_number),
        cache_logger_on_first_use=True,
    )
