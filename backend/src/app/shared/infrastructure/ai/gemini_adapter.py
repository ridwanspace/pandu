"""Google Gemini adapters for the LLM and embedding ports (``google-genai`` SDK).

Same contract as the OpenAI adapters: vendor exceptions become ProviderError
with a ``retryable`` verdict, usage is token counts only, prompt text never
leaves the call path.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from google import genai
from google.genai import errors as genai_errors
from google.genai import types as genai_types

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


def map_gemini_error(exc: Exception, *, provider: str, model: str) -> ProviderError:
    """Translate a google-genai exception into a domain ProviderError.

    Retryable: 429 and 5xx (``ServerError``); everything else client-side is
    final. Non-API exceptions (transport failures) are treated as transient.
    """
    if isinstance(exc, genai_errors.APIError):
        status = exc.code or 0
        retryable = status == 429 or status >= 500
        return ProviderError(
            f"{provider} API returned HTTP {status}: {exc.message}",
            provider=provider,
            model=model,
            retryable=retryable,
        )
    return ProviderError(
        f"{provider} call failed: {exc}", provider=provider, model=model, retryable=True
    )


def _split_messages(
    messages: Sequence[ChatMessage],
) -> tuple[str | None, list[genai_types.Content]]:
    """Gemini has no system role in ``contents``; system messages become the
    ``system_instruction`` and assistant turns map to role ``model``."""
    system_parts = [m.content for m in messages if m.role == "system"]
    contents = [
        genai_types.Content(
            role="model" if m.role == "assistant" else "user",
            parts=[genai_types.Part(text=m.content)],
        )
        for m in messages
        if m.role != "system"
    ]
    return ("\n\n".join(system_parts) or None, contents)


def _usage_from_metadata(
    metadata: genai_types.GenerateContentResponseUsageMetadata | None,
) -> TokenUsage:
    if metadata is None:
        return TokenUsage()
    return TokenUsage(
        prompt_tokens=metadata.prompt_token_count or 0,
        completion_tokens=metadata.candidates_token_count or 0,
    )


class GeminiChatAdapter:
    """Chat completions over ``google-genai`` (async surface, ``client.aio``)."""

    def __init__(
        self, *, model: ModelRef, api_key: str, client: genai.Client | None = None
    ) -> None:
        self._model = model
        self._client = client or genai.Client(api_key=api_key)

    @property
    def model(self) -> ModelRef:
        return self._model

    def _config(
        self, request: CompletionRequest, system: str | None
    ) -> genai_types.GenerateContentConfig:
        return genai_types.GenerateContentConfig(
            temperature=request.temperature,
            max_output_tokens=request.max_output_tokens,
            system_instruction=system,
        )

    async def complete(self, request: CompletionRequest) -> CompletionResult:
        system, contents = _split_messages(request.messages)
        try:
            response = await self._client.aio.models.generate_content(
                model=self._model.name,
                contents=contents,
                config=self._config(request, system),
            )
        except Exception as exc:
            raise map_gemini_error(
                exc, provider=self._model.provider, model=self._model.name
            ) from exc
        return CompletionResult(
            text=response.text or "",
            usage=_usage_from_metadata(response.usage_metadata),
            model=self._model,
        )

    async def stream(self, request: CompletionRequest) -> AsyncIterator[StreamEvent]:
        system, contents = _split_messages(request.messages)
        usage = TokenUsage()
        try:
            stream = await self._client.aio.models.generate_content_stream(
                model=self._model.name,
                contents=contents,
                config=self._config(request, system),
            )
            async for chunk in stream:
                if chunk.usage_metadata is not None:
                    usage = _usage_from_metadata(chunk.usage_metadata)
                if chunk.text:
                    yield StreamDelta(text=chunk.text)
        except Exception as exc:
            raise map_gemini_error(
                exc, provider=self._model.provider, model=self._model.name
            ) from exc
        yield StreamCompleted(usage=usage, model=self._model)


class GeminiEmbeddingAdapter:
    """Embeddings over ``google-genai``; dimensionality is requested via
    ``output_dimensionality`` so vectors match the pgvector column width."""

    def __init__(
        self,
        *,
        model: ModelRef,
        api_key: str,
        dimensions: int,
        client: genai.Client | None = None,
    ) -> None:
        self._model = model
        self._dimensions = dimensions
        self._client = client or genai.Client(api_key=api_key)

    @property
    def dimensions(self) -> int:
        return self._dimensions

    async def embed_batch(self, texts: Sequence[str]) -> EmbeddingBatch:
        if not texts:
            return EmbeddingBatch(vectors=(), usage=TokenUsage(), model=self._model)
        try:
            response = await self._client.aio.models.embed_content(
                model=self._model.name,
                contents=list(texts),
                config=genai_types.EmbedContentConfig(output_dimensionality=self._dimensions),
            )
        except Exception as exc:
            raise map_gemini_error(
                exc, provider=self._model.provider, model=self._model.name
            ) from exc
        embeddings = response.embeddings or []
        vectors = tuple(tuple(item.values or ()) for item in embeddings)
        # The embed API reports no per-call token usage; counts stay zero.
        return EmbeddingBatch(vectors=vectors, usage=TokenUsage(), model=self._model)
