"""SSE frame formatting and application-event mapping."""

from __future__ import annotations

import json
from decimal import Decimal
from uuid import uuid4

from app.modules.chat.application.events import (
    DoneEvent,
    ErrorEvent,
    SourcesEvent,
    TokenEvent,
    UsageEvent,
)
from app.modules.chat.domain.entities import Citation
from app.modules.chat.presentation.controllers import event_to_sse, sse
from app.shared.domain.values import TokenUsage


class TestSseFormatter:
    def test_frame_shape(self) -> None:
        assert sse("token", {"text": "hi"}) == 'event: token\ndata: {"text": "hi"}\n\n'

    def test_data_is_single_line_json(self) -> None:
        frame = sse("sources", {"citations": [{"marker": 1}]})
        _, data_line, tail = frame.split("\n", 2)
        assert tail == "\n"
        assert json.loads(data_line.removeprefix("data: ")) == {"citations": [{"marker": 1}]}


class TestEventMapping:
    def test_sources_event(self) -> None:
        citation = Citation(
            marker=1,
            chunk_id=uuid4(),
            document_id=uuid4(),
            filename="doc.md",
            heading_path=("A", "B"),
            snippet="snippet",
            score=0.7,
        )
        frame = event_to_sse(SourcesEvent(citations=(citation,)))
        assert frame.startswith("event: sources\n")
        payload = json.loads(frame.split("\n")[1].removeprefix("data: "))
        assert payload == {
            "citations": [
                {
                    "marker": 1,
                    "chunk_id": str(citation.chunk_id),
                    "document_id": str(citation.document_id),
                    "filename": "doc.md",
                    "heading_path": ["A", "B"],
                    "snippet": "snippet",
                    "score": 0.7,
                }
            ]
        }

    def test_token_event(self) -> None:
        assert event_to_sse(TokenEvent(text="abc")) == 'event: token\ndata: {"text": "abc"}\n\n'

    def test_usage_event_serializes_cost_as_string(self) -> None:
        frame = event_to_sse(
            UsageEvent(
                model="openai/gpt-4o-mini",
                usage=TokenUsage(prompt_tokens=10, completion_tokens=5),
                cost_usd=Decimal("0.000123"),
                latency_ms=42,
            )
        )
        payload = json.loads(frame.split("\n")[1].removeprefix("data: "))
        assert payload == {
            "model": "openai/gpt-4o-mini",
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "cost_usd": "0.000123",
            "latency_ms": 42,
        }

    def test_done_and_error_events(self) -> None:
        message_id = uuid4()
        done = event_to_sse(DoneEvent(message_id=message_id))
        assert json.loads(done.split("\n")[1].removeprefix("data: ")) == {
            "message_id": str(message_id)
        }
        error = event_to_sse(ErrorEvent(detail="nope"))
        assert error == 'event: error\ndata: {"detail": "nope"}\n\n'
