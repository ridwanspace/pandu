"""OpenAI adapters for the LLM and embedding ports.

The only place (together with the sibling adapters) where the ``openai`` SDK
is imported. All vendor exceptions are translated to
:class:`~app.shared.domain.errors.ProviderError` so the fallback chain can act
on ``retryable`` without knowing the vendor. Token counts are surfaced;
prompt text is never logged here or anywhere downstream.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import openai
from openai import AsyncOpenAI

from app.shared.domain.errors import ProviderError
from app.shared.domain.ports.embeddings import EmbeddingBatch
from app.shared.domain.ports.llm import (
    ChatMessage,
    CompletionRequest,
    CompletionResult,
    StreamCompleted,
    StreamDelta,
    StreamEvent,
)
from app.shared.domain.values import ModelRef, TokenUsage

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence

    from openai.types.chat import ChatCompletionMessageParam


def map_openai_error(exc: openai.OpenAIError, *, provider: str, model: str) -> ProviderError:
    """Translate an OpenAI SDK exception into a domain ProviderError.

    Retryable: rate limits (429), server errors (5xx), timeouts, connection
    failures. Not retryable: auth failures, bad requests, and any other 4xx —
    those are caller-side, so falling through to another provider would only
    mask a configuration bug.
    """
    if isinstance(exc, openai.APIStatusError):
        status = exc.status_code
        retryable = status == 429 or status >= 500
        return ProviderError(
            f"{provider} API returned HTTP {status}: {exc.message}",
            provider=provider,
            model=model,
            retryable=retryable,
        )
    # Timeouts and transport-level failures are transient by nature.
    return ProviderError(
        f"{provider} call failed: {exc}", provider=provider, model=model, retryable=True
    )


def _to_openai_messages(messages: Sequence[ChatMessage]) -> list[ChatCompletionMessageParam]:
    out: list[ChatCompletionMessageParam] = []
    for message in messages:
        if message.role == "system":
            out.append({"role": "system", "content": message.content})
        elif message.role == "assistant":
            out.append({"role": "assistant", "content": message.content})
        else:
            out.append({"role": "user", "content": message.content})
    return out


class OpenAIChatAdapter:
    """Chat completions over ``openai.AsyncOpenAI``.

    ``use_max_completion_tokens`` selects the modern token-limit parameter
    (required by o-series models); OpenAI-compatible endpoints that only
    understand the legacy ``max_tokens`` set it to False (see
    ``openai_compatible.py``).
    """

    def __init__(
        self,
        *,
        model: ModelRef,
        api_key: str,
        base_url: str | None = None,
        client: AsyncOpenAI | None = None,
        use_max_completion_tokens: bool = True,
    ) -> None:
        self._model = model
        self._client = client or AsyncOpenAI(api_key=api_key, base_url=base_url)
        self._use_max_completion_tokens = use_max_completion_tokens

    @property
    def model(self) -> ModelRef:
        return self._model

    async def complete(self, request: CompletionRequest) -> CompletionResult:
        try:
            response = await self._client.chat.completions.create(
                model=self._model.name,
                messages=_to_openai_messages(request.messages),
                temperature=request.temperature,
                max_completion_tokens=(
                    request.max_output_tokens if self._use_max_completion_tokens else openai.omit
                ),
                max_tokens=(
                    openai.omit if self._use_max_completion_tokens else request.max_output_tokens
                ),
            )
        except openai.OpenAIError as exc:
            raise map_openai_error(
                exc, provider=self._model.provider, model=self._model.name
            ) from exc

        text = response.choices[0].message.content or "" if response.choices else ""
        usage = TokenUsage()
        if response.usage is not None:
            usage = TokenUsage(
                prompt_tokens=response.usage.prompt_tokens,
                completion_tokens=response.usage.completion_tokens,
            )
        return CompletionResult(text=text, usage=usage, model=self._model)

    async def stream(self, request: CompletionRequest) -> AsyncIterator[StreamEvent]:
        usage = TokenUsage()
        try:
            stream = await self._client.chat.completions.create(
                model=self._model.name,
                messages=_to_openai_messages(request.messages),
                temperature=request.temperature,
                max_completion_tokens=(
                    request.max_output_tokens if self._use_max_completion_tokens else openai.omit
                ),
                max_tokens=(
                    openai.omit if self._use_max_completion_tokens else request.max_output_tokens
                ),
                stream=True,
                stream_options={"include_usage": True},
            )
            async for chunk in stream:
                if chunk.usage is not None:
                    usage = TokenUsage(
                        prompt_tokens=chunk.usage.prompt_tokens,
                        completion_tokens=chunk.usage.completion_tokens,
                    )
                if chunk.choices and chunk.choices[0].delta.content:
                    yield StreamDelta(text=chunk.choices[0].delta.content)
        except openai.OpenAIError as exc:
            raise map_openai_error(
                exc, provider=self._model.provider, model=self._model.name
            ) from exc
        yield StreamCompleted(usage=usage, model=self._model)


class OpenAIEmbeddingAdapter:
    """Embeddings over ``openai.AsyncOpenAI``.

    ``send_dimensions`` forwards the requested dimensionality to the API
    (supported by text-embedding-3-*); OpenAI-compatible servers that reject
    the parameter disable it and must be configured to emit the right size.
    """

    def __init__(
        self,
        *,
        model: ModelRef,
        api_key: str,
        dimensions: int,
        base_url: str | None = None,
        client: AsyncOpenAI | None = None,
        send_dimensions: bool = True,
    ) -> None:
        self._model = model
        self._dimensions = dimensions
        self._client = client or AsyncOpenAI(api_key=api_key, base_url=base_url)
        self._send_dimensions = send_dimensions

    @property
    def dimensions(self) -> int:
        return self._dimensions

    async def embed_batch(self, texts: Sequence[str]) -> EmbeddingBatch:
        if not texts:
            return EmbeddingBatch(vectors=(), usage=TokenUsage(), model=self._model)
        try:
            response = await self._client.embeddings.create(
                model=self._model.name,
                input=list(texts),
                dimensions=self._dimensions if self._send_dimensions else openai.omit,
                encoding_format="float",
            )
        except openai.OpenAIError as exc:
            raise map_openai_error(
                exc, provider=self._model.provider, model=self._model.name
            ) from exc

        # The API documents order preservation, but sort by index defensively.
        vectors = tuple(
            tuple(item.embedding) for item in sorted(response.data, key=lambda item: item.index)
        )
        usage = TokenUsage(prompt_tokens=response.usage.prompt_tokens)
        return EmbeddingBatch(vectors=vectors, usage=usage, model=self._model)
