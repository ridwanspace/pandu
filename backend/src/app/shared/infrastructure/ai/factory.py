"""Provider factory: resolves ``provider/model`` strings to adapters.

Settings are injected by the composition root; keys are validated at *build*
time (never at import time) so a missing credential fails fast with an
actionable message instead of a mid-request 401.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.shared.domain.errors import InvalidInputError
from app.shared.domain.values import ModelRef
from app.shared.infrastructure.ai.gemini_adapter import GeminiChatAdapter, GeminiEmbeddingAdapter
from app.shared.infrastructure.ai.openai_adapter import (
    OpenAIChatAdapter,
    OpenAIEmbeddingAdapter,
)
from app.shared.infrastructure.ai.openai_compatible import (
    OpenAICompatibleChatAdapter,
    OpenAICompatibleEmbeddingAdapter,
)
from app.shared.infrastructure.ai.rerankers import (
    CohereReranker,
    JinaReranker,
    LocalCrossEncoderReranker,
    NoopReranker,
)

if TYPE_CHECKING:
    from app.config import Settings
    from app.shared.domain.ports.embeddings import EmbeddingProvider
    from app.shared.domain.ports.llm import LLMProvider
    from app.shared.domain.ports.reranker import Reranker

LLM_PROVIDERS = ("openai", "gemini", "deepseek", "compat")
EMBEDDING_PROVIDERS = ("openai", "gemini", "compat")
RERANKER_KINDS = ("none", "cohere", "jina", "local")


def _parse_ref(model_ref: str) -> ModelRef:
    try:
        return ModelRef.parse(model_ref)
    except ValueError as exc:
        raise InvalidInputError(str(exc)) from exc


def _require(value: str, setting_name: str, *, needed_for: str) -> str:
    if not value:
        msg = f"{setting_name} is not set but is required for {needed_for}"
        raise InvalidInputError(msg)
    return value


class ProviderFactory:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def build_llm(self, model_ref: str) -> LLMProvider:
        ref = _parse_ref(model_ref)
        settings = self._settings
        if ref.provider == "openai":
            return OpenAIChatAdapter(
                model=ref,
                api_key=_require(settings.openai_api_key, "OPENAI_API_KEY", needed_for=str(ref)),
            )
        if ref.provider == "gemini":
            return GeminiChatAdapter(
                model=ref,
                api_key=_require(settings.gemini_api_key, "GEMINI_API_KEY", needed_for=str(ref)),
            )
        if ref.provider == "deepseek":
            return OpenAICompatibleChatAdapter(
                model=ref,
                base_url=settings.deepseek_base_url,
                api_key=_require(
                    settings.deepseek_api_key, "DEEPSEEK_API_KEY", needed_for=str(ref)
                ),
            )
        if ref.provider == "compat":
            return OpenAICompatibleChatAdapter(
                model=ref,
                base_url=_require(
                    settings.openai_compatible_base_url,
                    "OPENAI_COMPATIBLE_BASE_URL",
                    needed_for=str(ref),
                ),
                api_key=settings.openai_compatible_api_key,
            )
        msg = f"unknown LLM provider {ref.provider!r}; expected one of {LLM_PROVIDERS}"
        raise InvalidInputError(msg)

    def build_embeddings(self, model_ref: str) -> EmbeddingProvider:
        ref = _parse_ref(model_ref)
        settings = self._settings
        if ref.provider == "openai":
            return OpenAIEmbeddingAdapter(
                model=ref,
                api_key=_require(settings.openai_api_key, "OPENAI_API_KEY", needed_for=str(ref)),
                dimensions=settings.embedding_dimensions,
            )
        if ref.provider == "gemini":
            return GeminiEmbeddingAdapter(
                model=ref,
                api_key=_require(settings.gemini_api_key, "GEMINI_API_KEY", needed_for=str(ref)),
                dimensions=settings.embedding_dimensions,
            )
        if ref.provider == "compat":
            return OpenAICompatibleEmbeddingAdapter(
                model=ref,
                base_url=_require(
                    settings.openai_compatible_base_url,
                    "OPENAI_COMPATIBLE_BASE_URL",
                    needed_for=str(ref),
                ),
                api_key=settings.openai_compatible_api_key,
                dimensions=settings.embedding_dimensions,
            )
        if ref.provider == "deepseek":
            msg = "deepseek has no embedding API; configure AI_EMBED_MODEL with openai or gemini"
            raise InvalidInputError(msg)
        msg = f"unknown embedding provider {ref.provider!r}; expected one of {EMBEDDING_PROVIDERS}"
        raise InvalidInputError(msg)

    def build_reranker(self, kind: str) -> Reranker:
        settings = self._settings
        if kind == "none":
            return NoopReranker()
        if kind == "cohere":
            return CohereReranker(
                api_key=_require(settings.cohere_api_key, "COHERE_API_KEY", needed_for="cohere")
            )
        if kind == "jina":
            return JinaReranker(
                api_key=_require(settings.jina_api_key, "JINA_API_KEY", needed_for="jina")
            )
        if kind == "local":
            return LocalCrossEncoderReranker(model_name=settings.local_reranker_model)
        msg = f"unknown reranker {kind!r}; expected one of {RERANKER_KINDS}"
        raise InvalidInputError(msg)
