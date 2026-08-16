"""Reranker adapters (ADR-010): no-op default, hosted Cohere/Jina over httpx,
and an optional local cross-encoder behind the ``rerank-local`` extra.

Hosted adapters accept an injected ``httpx.AsyncClient`` so unit tests can use
``httpx.MockTransport``; without one they own a client with a sane timeout.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import httpx

from app.shared.domain.errors import InvalidInputError, ProviderError
from app.shared.domain.ports.reranker import RerankedItem

if TYPE_CHECKING:
    from collections.abc import Sequence

    from app.shared.domain.ports.reranker import RerankCandidate

COHERE_RERANK_URL = "https://api.cohere.com/v2/rerank"
JINA_RERANK_URL = "https://api.jina.ai/v1/rerank"

_DEFAULT_TIMEOUT_SECONDS = 30.0


class NoopReranker:
    """Pass-through: keeps the hybrid+RRF order, scores nothing. The platform
    default — reranking is an opt-in quality knob, not a dependency."""

    @property
    def name(self) -> str:
        return "none"

    async def rerank(
        self, query: str, candidates: Sequence[RerankCandidate], *, top_k: int
    ) -> list[RerankedItem]:
        return [RerankedItem(id=c.id, score=0.0) for c in candidates[:top_k]]


def _map_rerank_status(provider: str, model: str, status: int) -> ProviderError:
    retryable = status == 429 or status >= 500
    return ProviderError(
        f"{provider} rerank API returned HTTP {status}",
        provider=provider,
        model=model,
        retryable=retryable,
    )


class _HostedReranker:
    """Shared POST/parse logic for v2-style rerank APIs (Cohere and Jina both
    return ``results: [{index, relevance_score}]``)."""

    _provider: str = "hosted"
    _url: str = ""

    def __init__(self, *, api_key: str, model: str, client: httpx.AsyncClient | None) -> None:
        self._api_key = api_key
        self._model = model
        self._client = client or httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT_SECONDS)

    @property
    def name(self) -> str:
        return self._provider

    async def rerank(
        self, query: str, candidates: Sequence[RerankCandidate], *, top_k: int
    ) -> list[RerankedItem]:
        if not candidates:
            return []
        payload = {
            "model": self._model,
            "query": query,
            "documents": [c.text for c in candidates],
            "top_n": min(top_k, len(candidates)),
        }
        headers = {"Authorization": f"Bearer {self._api_key}"}
        try:
            response = await self._client.post(self._url, json=payload, headers=headers)
        except httpx.HTTPError as exc:
            raise ProviderError(
                f"{self._provider} rerank call failed: {exc}",
                provider=self._provider,
                model=self._model,
                retryable=True,
            ) from exc
        if response.status_code >= 400:
            raise _map_rerank_status(self._provider, self._model, response.status_code)
        body: Any = response.json()
        items = [
            RerankedItem(
                id=candidates[int(result["index"])].id,
                score=float(result["relevance_score"]),
            )
            for result in body["results"]
        ]
        return items[:top_k]


class CohereReranker(_HostedReranker):
    _provider = "cohere"
    _url = COHERE_RERANK_URL

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "rerank-v3.5",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(api_key=api_key, model=model, client=client)


class JinaReranker(_HostedReranker):
    _provider = "jina"
    _url = JINA_RERANK_URL

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "jina-reranker-v2-base-multilingual",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(api_key=api_key, model=model, client=client)


class LocalCrossEncoderReranker:
    """Cross-encoder reranking on local hardware via sentence-transformers.

    The import is deferred and guarded: the dependency pulls torch, so it is an
    optional extra and its absence must fail with an actionable message, not an
    ImportError at startup. Model load and inference are synchronous CPU/GPU
    work, so both run in a worker thread.
    """

    def __init__(self, *, model_name: str) -> None:
        self._model_name = model_name
        self._model: Any = None

    @property
    def name(self) -> str:
        return "local"

    def _load_model(self) -> Any:
        if self._model is None:
            try:
                from sentence_transformers import CrossEncoder
            except ImportError as exc:
                msg = (
                    "sentence-transformers is not installed; the local reranker "
                    "requires the 'rerank-local' extra (uv sync --extra rerank-local)"
                )
                raise InvalidInputError(msg) from exc
            self._model = CrossEncoder(self._model_name)
        return self._model

    async def rerank(
        self, query: str, candidates: Sequence[RerankCandidate], *, top_k: int
    ) -> list[RerankedItem]:
        if not candidates:
            return []
        model = await asyncio.to_thread(self._load_model)
        pairs = [(query, c.text) for c in candidates]
        scores = await asyncio.to_thread(model.predict, pairs)
        ranked = sorted(
            zip(candidates, scores, strict=True), key=lambda pair: float(pair[1]), reverse=True
        )
        return [RerankedItem(id=c.id, score=float(score)) for c, score in ranked[:top_k]]
