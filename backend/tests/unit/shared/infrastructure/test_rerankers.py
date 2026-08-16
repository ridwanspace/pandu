"""Reranker adapters: Noop pass-through, hosted adapters over MockTransport,
HTTP error mapping, and the guarded local import."""

from __future__ import annotations

import importlib.util
import json
from typing import TYPE_CHECKING

import httpx
import pytest

from app.shared.domain.errors import InvalidInputError, ProviderError
from app.shared.domain.ports.reranker import RerankCandidate
from app.shared.infrastructure.ai.rerankers import (
    COHERE_RERANK_URL,
    JINA_RERANK_URL,
    CohereReranker,
    JinaReranker,
    LocalCrossEncoderReranker,
    NoopReranker,
)

if TYPE_CHECKING:
    from collections.abc import Callable

CANDIDATES = [
    RerankCandidate(id="c1", text="alpha"),
    RerankCandidate(id="c2", text="beta"),
    RerankCandidate(id="c3", text="gamma"),
]


class TestNoopReranker:
    async def test_preserves_order_and_truncates(self) -> None:
        reranker = NoopReranker()
        items = await reranker.rerank("query", CANDIDATES, top_k=2)
        assert [(item.id, item.score) for item in items] == [("c1", 0.0), ("c2", 0.0)]
        assert reranker.name == "none"

    async def test_top_k_larger_than_candidates(self) -> None:
        items = await NoopReranker().rerank("query", CANDIDATES, top_k=10)
        assert len(items) == 3


def _mock_client(
    handler: Callable[[httpx.Request], httpx.Response],
) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


class TestCohereReranker:
    async def test_reranks_via_v2_endpoint(self) -> None:
        seen: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["url"] = str(request.url)
            seen["auth"] = request.headers["Authorization"]
            seen["payload"] = json.loads(request.content)
            return httpx.Response(
                200,
                json={
                    "results": [
                        {"index": 2, "relevance_score": 0.95},
                        {"index": 0, "relevance_score": 0.40},
                    ]
                },
            )

        reranker = CohereReranker(api_key="secret-key", client=_mock_client(handler))
        items = await reranker.rerank("query", CANDIDATES, top_k=2)

        assert seen["url"] == COHERE_RERANK_URL
        assert seen["auth"] == "Bearer secret-key"
        payload = seen["payload"]
        assert payload == {
            "model": "rerank-v3.5",
            "query": "query",
            "documents": ["alpha", "beta", "gamma"],
            "top_n": 2,
        }
        assert [(item.id, item.score) for item in items] == [("c3", 0.95), ("c1", 0.40)]
        assert reranker.name == "cohere"

    async def test_empty_candidates_skip_http(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise AssertionError("no HTTP call expected")

        reranker = CohereReranker(api_key="k", client=_mock_client(handler))
        assert await reranker.rerank("query", [], top_k=5) == []

    @pytest.mark.parametrize(
        ("status", "retryable"), [(429, True), (500, True), (503, True), (400, False), (401, False)]
    )
    async def test_http_error_mapping(self, status: int, retryable: bool) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(status, json={"message": "nope"})

        reranker = CohereReranker(api_key="k", client=_mock_client(handler))
        with pytest.raises(ProviderError) as exc_info:
            await reranker.rerank("query", CANDIDATES, top_k=2)
        assert exc_info.value.retryable is retryable
        assert exc_info.value.provider == "cohere"

    async def test_transport_error_is_retryable(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("refused")

        reranker = CohereReranker(api_key="k", client=_mock_client(handler))
        with pytest.raises(ProviderError) as exc_info:
            await reranker.rerank("query", CANDIDATES, top_k=1)
        assert exc_info.value.retryable is True


class TestJinaReranker:
    async def test_reranks_via_v1_endpoint(self) -> None:
        seen: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["url"] = str(request.url)
            seen["payload"] = json.loads(request.content)
            return httpx.Response(200, json={"results": [{"index": 1, "relevance_score": 0.8}]})

        reranker = JinaReranker(api_key="j-key", client=_mock_client(handler))
        items = await reranker.rerank("query", CANDIDATES, top_k=1)

        assert seen["url"] == JINA_RERANK_URL
        payload = seen["payload"]
        assert isinstance(payload, dict)
        assert payload["model"] == "jina-reranker-v2-base-multilingual"
        assert payload["top_n"] == 1
        assert [(item.id, item.score) for item in items] == [("c2", 0.8)]
        assert reranker.name == "jina"


@pytest.mark.skipif(
    importlib.util.find_spec("sentence_transformers") is not None,
    reason="sentence-transformers installed; the guarded-import path cannot fire",
)
class TestLocalCrossEncoderReranker:
    async def test_missing_dependency_raises_actionable_error(self) -> None:
        reranker = LocalCrossEncoderReranker(model_name="BAAI/bge-reranker-v2-m3")
        with pytest.raises(InvalidInputError, match="rerank-local"):
            await reranker.rerank("query", CANDIDATES, top_k=2)
