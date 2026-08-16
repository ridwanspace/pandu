"""Offline embedding provider: feature-hashed character n-grams.

Selected with ``AI_EMBED_MODEL=hash/ngram``. This is NOT a semantic embedding
model — it is a deterministic bag-of-character-n-grams vector space (signed
feature hashing, L2-normalized), so cosine similarity reflects surface overlap,
not meaning. It exists for two honest reasons:

- **Keyless quickstart / CI**: the full stack (ingest -> hybrid retrieval ->
  chat) runs with zero embedding credentials; the lexical arm still does real
  full-text work and the dense arm degrades to n-gram similarity.
- **Provider asymmetry**: some chat vendors (e.g. DeepSeek) ship no embedding
  API; this keeps single-key deployments functional until a real embedding
  provider is configured.

No network, no model download, any target dimension.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Sequence

from app.shared.domain.errors import InvalidInputError
from app.shared.domain.ports.embeddings import EmbeddingBatch, Vector
from app.shared.domain.values import ModelRef, TokenUsage

_NGRAM_SIZES = (3, 4, 5)


def _ngrams(text: str) -> list[str]:
    normalized = " ".join(text.lower().split())
    grams: list[str] = []
    for size in _NGRAM_SIZES:
        grams.extend(normalized[i : i + size] for i in range(max(len(normalized) - size + 1, 0)))
    return grams


class HashingEmbedder:
    """EmbeddingProvider adapter — signed feature hashing over char n-grams."""

    def __init__(self, *, dimensions: int, model_name: str = "ngram") -> None:
        if dimensions <= 0:
            msg = f"embedding dimensions must be positive, got {dimensions}"
            raise InvalidInputError(msg)
        self._dimensions = dimensions
        self._model = ModelRef(provider="hash", name=model_name)

    @property
    def dimensions(self) -> int:
        return self._dimensions

    def _embed_one(self, text: str) -> Vector:
        weights = [0.0] * self._dimensions
        for gram in _ngrams(text):
            digest = hashlib.blake2b(gram.encode(), digest_size=8).digest()
            bucket = int.from_bytes(digest[:7], "big") % self._dimensions
            sign = 1.0 if digest[7] & 1 else -1.0
            weights[bucket] += sign
        norm = math.sqrt(sum(w * w for w in weights))
        if norm == 0.0:
            # Degenerate input (empty/whitespace): a fixed unit vector keeps
            # pgvector's cosine operator well-defined.
            weights[0] = 1.0
            return tuple(weights)
        return tuple(w / norm for w in weights)

    async def embed_batch(self, texts: Sequence[str]) -> EmbeddingBatch:
        vectors = tuple(self._embed_one(text) for text in texts)
        # Rough word count keeps the cost meter's usage fields meaningful;
        # the hash model itself is free.
        prompt_tokens = sum(len(text.split()) for text in texts)
        return EmbeddingBatch(
            vectors=vectors,
            usage=TokenUsage(prompt_tokens=prompt_tokens, completion_tokens=0),
            model=self._model,
        )
