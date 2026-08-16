"""Embedding provider port.

Chat and embedding providers are configured independently (``AI_CHAT_MODEL`` vs
``AI_EMBED_MODEL``) — e.g. DeepSeek has no embedding API, so a DeepSeek chat
deployment still embeds with OpenAI or Gemini. That asymmetry is exactly why
this is a separate port.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from app.shared.domain.values import ModelRef, TokenUsage

Vector = tuple[float, ...]


@dataclass(frozen=True, slots=True)
class EmbeddingBatch:
    vectors: tuple[Vector, ...]
    usage: TokenUsage
    model: ModelRef


class EmbeddingProvider(Protocol):
    @property
    def dimensions(self) -> int: ...

    async def embed_batch(self, texts: Sequence[str]) -> EmbeddingBatch: ...
