"""Reranker port. Default binding is a no-op (hybrid + RRF order passes through);
opt-in adapters: Cohere / Jina (hosted) or a local cross-encoder. See ADR-010."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class RerankCandidate:
    id: str
    text: str


@dataclass(frozen=True, slots=True)
class RerankedItem:
    id: str
    score: float


class Reranker(Protocol):
    @property
    def name(self) -> str: ...

    async def rerank(
        self, query: str, candidates: Sequence[RerankCandidate], *, top_k: int
    ) -> list[RerankedItem]:
        """Return the ``top_k`` candidates by relevance, best first."""
        ...
