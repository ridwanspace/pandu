"""Offline chat provider: deterministic extractive answers, zero API keys.

Selected with ``AI_CHAT_MODEL=mock/extractive``. Paired with the offline
``hash/ngram`` embedder this runs the entire platform — ingest, hybrid
retrieval, streaming chat with citations, cost metering — with no provider
account at all, which is what `make up` demos and CI rely on.

It is NOT a language model: it extracts the leading sentences of the top
numbered context blocks from the grounded prompt and cites them. Grounded by
construction, deterministic by construction, and obviously labelled as mock
in the usage footer (model ``mock/extractive``).
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator

from app.shared.domain.ports.llm import (
    CompletionRequest,
    CompletionResult,
    StreamCompleted,
    StreamDelta,
    StreamEvent,
)
from app.shared.domain.values import ModelRef, TokenUsage

_BLOCK_RE = re.compile(r"^\[(\d+)\] \(.*\)$")
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
_MAX_CITED_BLOCKS = 2
_SENTENCES_PER_BLOCK = 2


def _extract_blocks(prompt: str) -> list[tuple[int, str]]:
    """Parse the numbered context blocks out of the grounded user message."""
    blocks: list[tuple[int, str]] = []
    marker: int | None = None
    lines: list[str] = []
    for raw in prompt.splitlines():
        match = _BLOCK_RE.match(raw)
        if match:
            if marker is not None:
                blocks.append((marker, " ".join(lines).strip()))
            marker = int(match.group(1))
            lines = []
        elif raw.startswith("Question:"):
            break
        elif marker is not None:
            lines.append(raw.strip())
    if marker is not None:
        blocks.append((marker, " ".join(lines).strip()))
    return [(m, text) for m, text in blocks if text]


def _leading_sentences(text: str, count: int) -> str:
    sentences = _SENTENCE_RE.split(text)
    return " ".join(sentences[:count]).strip()


class MockExtractiveLLM:
    """LLMProvider adapter for keyless demos and CI."""

    def __init__(self) -> None:
        self._model = ModelRef(provider="mock", name="extractive")

    def _answer(self, request: CompletionRequest) -> str:
        prompt = request.messages[-1].content if request.messages else ""
        blocks = _extract_blocks(prompt)
        if not blocks:
            return "The provided context does not contain the answer."
        parts = [
            f"{_leading_sentences(text, _SENTENCES_PER_BLOCK)} [{marker}]"
            for marker, text in blocks[:_MAX_CITED_BLOCKS]
        ]
        return "According to the retrieved context: " + " ".join(parts)

    def _usage(self, request: CompletionRequest, answer: str) -> TokenUsage:
        prompt_chars = sum(len(m.content) for m in request.messages)
        return TokenUsage(prompt_tokens=prompt_chars // 4, completion_tokens=len(answer) // 4)

    async def complete(self, request: CompletionRequest) -> CompletionResult:
        answer = self._answer(request)
        return CompletionResult(text=answer, usage=self._usage(request, answer), model=self._model)

    async def stream(self, request: CompletionRequest) -> AsyncIterator[StreamEvent]:
        answer = self._answer(request)
        words = answer.split(" ")
        for start in range(0, len(words), 6):
            yield StreamDelta(text=" ".join(words[start : start + 6]) + " ")
        yield StreamCompleted(usage=self._usage(request, answer), model=self._model)
