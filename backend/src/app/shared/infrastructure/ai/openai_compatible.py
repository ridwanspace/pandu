"""Adapters for OpenAI-compatible endpoints (DeepSeek, Ollama, vLLM, Groq, ...).

Thin parameterizations of the OpenAI adapters: a ``base_url`` plus an API key
(some local servers need none — a placeholder keeps the SDK happy), and the
legacy ``max_tokens`` parameter because most compatible servers do not accept
``max_completion_tokens``. DeepSeek is chat-only; embeddings stay on OpenAI or
Gemini (see the provider factory).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.shared.infrastructure.ai.openai_adapter import (
    OpenAIChatAdapter,
    OpenAIEmbeddingAdapter,
)

if TYPE_CHECKING:
    from openai import AsyncOpenAI

    from app.shared.domain.values import ModelRef

_PLACEHOLDER_KEY = "unused"  # OpenAI SDK rejects an empty api_key outright.


class OpenAICompatibleChatAdapter(OpenAIChatAdapter):
    def __init__(
        self,
        *,
        model: ModelRef,
        base_url: str,
        api_key: str = "",
        client: AsyncOpenAI | None = None,
    ) -> None:
        super().__init__(
            model=model,
            api_key=api_key or _PLACEHOLDER_KEY,
            base_url=base_url,
            client=client,
            use_max_completion_tokens=False,
        )


class OpenAICompatibleEmbeddingAdapter(OpenAIEmbeddingAdapter):
    def __init__(
        self,
        *,
        model: ModelRef,
        base_url: str,
        dimensions: int,
        api_key: str = "",
        client: AsyncOpenAI | None = None,
    ) -> None:
        super().__init__(
            model=model,
            api_key=api_key or _PLACEHOLDER_KEY,
            dimensions=dimensions,
            base_url=base_url,
            client=client,
            send_dimensions=False,
        )
