"""ProviderFactory resolution: adapter selection, key checks, error paths.

No network: adapter construction only builds SDK clients.
"""

from __future__ import annotations

import pytest

from app.config import Settings
from app.shared.domain.errors import InvalidInputError
from app.shared.infrastructure.ai.factory import ProviderFactory
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


def make_settings(**overrides: object) -> Settings:
    defaults: dict[str, object] = {
        "_env_file": None,
        "openai_api_key": "",
        "gemini_api_key": "",
        "deepseek_api_key": "",
        "openai_compatible_base_url": "",
        "openai_compatible_api_key": "",
        "cohere_api_key": "",
        "jina_api_key": "",
    }
    defaults.update(overrides)
    return Settings(**defaults)  # type: ignore[arg-type]


class TestBuildLLM:
    def test_openai(self) -> None:
        factory = ProviderFactory(make_settings(openai_api_key="sk-test"))
        provider = factory.build_llm("openai/gpt-4o-mini")
        assert type(provider) is OpenAIChatAdapter
        assert provider.model.name == "gpt-4o-mini"

    def test_gemini(self) -> None:
        factory = ProviderFactory(make_settings(gemini_api_key="g-test"))
        provider = factory.build_llm("gemini/gemini-2.0-flash")
        assert isinstance(provider, GeminiChatAdapter)

    def test_deepseek_is_openai_compatible(self) -> None:
        factory = ProviderFactory(make_settings(deepseek_api_key="d-test"))
        provider = factory.build_llm("deepseek/deepseek-chat")
        assert isinstance(provider, OpenAICompatibleChatAdapter)

    def test_compat_requires_base_url(self) -> None:
        factory = ProviderFactory(make_settings())
        with pytest.raises(InvalidInputError, match="OPENAI_COMPATIBLE_BASE_URL"):
            factory.build_llm("compat/llama-3.3-70b")

    def test_compat_works_without_api_key(self) -> None:
        factory = ProviderFactory(
            make_settings(openai_compatible_base_url="http://localhost:11434/v1")
        )
        provider = factory.build_llm("compat/llama-3.3-70b")
        assert isinstance(provider, OpenAICompatibleChatAdapter)

    def test_unknown_provider(self) -> None:
        factory = ProviderFactory(make_settings())
        with pytest.raises(InvalidInputError, match="unknown LLM provider"):
            factory.build_llm("anthropic/claude-sonnet")

    def test_malformed_ref(self) -> None:
        factory = ProviderFactory(make_settings())
        with pytest.raises(InvalidInputError, match="provider/model"):
            factory.build_llm("gpt-4o-mini")

    def test_missing_openai_key(self) -> None:
        factory = ProviderFactory(make_settings())
        with pytest.raises(InvalidInputError, match="OPENAI_API_KEY"):
            factory.build_llm("openai/gpt-4o-mini")


class TestBuildEmbeddings:
    def test_openai_with_configured_dimensions(self) -> None:
        factory = ProviderFactory(
            make_settings(openai_api_key="sk-test", embedding_dimensions=1536)
        )
        provider = factory.build_embeddings("openai/text-embedding-3-small")
        assert type(provider) is OpenAIEmbeddingAdapter
        assert provider.dimensions == 1536

    def test_gemini(self) -> None:
        factory = ProviderFactory(make_settings(gemini_api_key="g-test"))
        provider = factory.build_embeddings("gemini/gemini-embedding-001")
        assert isinstance(provider, GeminiEmbeddingAdapter)

    def test_compat(self) -> None:
        factory = ProviderFactory(
            make_settings(openai_compatible_base_url="http://localhost:11434/v1")
        )
        provider = factory.build_embeddings("compat/nomic-embed-text")
        assert isinstance(provider, OpenAICompatibleEmbeddingAdapter)

    def test_deepseek_has_no_embeddings(self) -> None:
        factory = ProviderFactory(make_settings(deepseek_api_key="d-test"))
        with pytest.raises(InvalidInputError, match="no embedding API"):
            factory.build_embeddings("deepseek/deepseek-chat")

    def test_unknown_provider(self) -> None:
        factory = ProviderFactory(make_settings())
        with pytest.raises(InvalidInputError, match="unknown embedding provider"):
            factory.build_embeddings("voyage/voyage-3")


class TestBuildReranker:
    def test_none(self) -> None:
        assert isinstance(ProviderFactory(make_settings()).build_reranker("none"), NoopReranker)

    def test_cohere(self) -> None:
        factory = ProviderFactory(make_settings(cohere_api_key="c-test"))
        assert isinstance(factory.build_reranker("cohere"), CohereReranker)

    def test_cohere_missing_key(self) -> None:
        with pytest.raises(InvalidInputError, match="COHERE_API_KEY"):
            ProviderFactory(make_settings()).build_reranker("cohere")

    def test_jina(self) -> None:
        factory = ProviderFactory(make_settings(jina_api_key="j-test"))
        assert isinstance(factory.build_reranker("jina"), JinaReranker)

    def test_local(self) -> None:
        factory = ProviderFactory(make_settings())
        reranker = factory.build_reranker("local")
        assert isinstance(reranker, LocalCrossEncoderReranker)

    def test_unknown_kind(self) -> None:
        with pytest.raises(InvalidInputError, match="unknown reranker"):
            ProviderFactory(make_settings()).build_reranker("bm25")
