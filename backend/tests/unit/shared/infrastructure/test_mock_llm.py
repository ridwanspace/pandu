"""MockExtractiveLLM: deterministic, grounded-by-construction, clearly labelled."""

from __future__ import annotations

from app.shared.domain.ports.llm import (
    ChatMessage,
    CompletionRequest,
    StreamCompleted,
    StreamDelta,
)
from app.shared.infrastructure.ai.mock_llm import MockExtractiveLLM

GROUNDED_PROMPT = """Context:

[1] (guide.md — Access > Reauthentication)
Reauthentication must happen every 12 hours. Sessions also end after 30 minutes idle. \
Extra detail sentence that should not be quoted.

[2] (controls.md — Audit)
Audit records are kept for 90 days online. One year in cold storage follows.

Question: How often is reauthentication required?"""


def _request(content: str) -> CompletionRequest:
    return CompletionRequest(
        messages=(
            ChatMessage(role="system", content="rules"),
            ChatMessage(role="user", content=content),
        )
    )


async def test_extracts_leading_sentences_with_markers() -> None:
    result = await MockExtractiveLLM().complete(_request(GROUNDED_PROMPT))
    assert "Reauthentication must happen every 12 hours." in result.text
    assert "[1]" in result.text
    assert "[2]" in result.text
    assert "should not be quoted" not in result.text
    assert str(result.model) == "mock/extractive"
    assert result.usage.prompt_tokens > 0
    assert result.usage.completion_tokens > 0


async def test_deterministic() -> None:
    first = await MockExtractiveLLM().complete(_request(GROUNDED_PROMPT))
    second = await MockExtractiveLLM().complete(_request(GROUNDED_PROMPT))
    assert first.text == second.text


async def test_no_context_yields_grounded_refusal() -> None:
    result = await MockExtractiveLLM().complete(_request("Question: anything?"))
    assert "does not contain" in result.text


async def test_stream_reassembles_to_complete_answer() -> None:
    provider = MockExtractiveLLM()
    events = [event async for event in provider.stream(_request(GROUNDED_PROMPT))]
    completed = events[-1]
    assert isinstance(completed, StreamCompleted)
    text = "".join(e.text for e in events if isinstance(e, StreamDelta)).strip()
    expected = (await provider.complete(_request(GROUNDED_PROMPT))).text
    assert text == expected
