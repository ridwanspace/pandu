"""HashingEmbedder: deterministic, unit-norm, dimension-exact, overlap-sensitive."""

from __future__ import annotations

import math

import pytest

from app.shared.domain.errors import InvalidInputError
from app.shared.infrastructure.ai.hash_embeddings import HashingEmbedder


def _cosine(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


async def test_embeds_to_requested_dimensions_with_unit_norm() -> None:
    embedder = HashingEmbedder(dimensions=64)
    batch = await embedder.embed_batch(["access control policy for audit logs"])
    (vector,) = batch.vectors
    assert len(vector) == 64
    assert embedder.dimensions == 64
    assert math.isclose(math.sqrt(sum(v * v for v in vector)), 1.0, rel_tol=1e-9)


async def test_deterministic_across_instances() -> None:
    text = "multi-factor authentication at AAL2"
    first = await HashingEmbedder(dimensions=128).embed_batch([text])
    second = await HashingEmbedder(dimensions=128).embed_batch([text])
    assert first.vectors == second.vectors


async def test_surface_overlap_orders_similarity() -> None:
    embedder = HashingEmbedder(dimensions=512)
    batch = await embedder.embed_batch(
        [
            "access control policies",
            "access control policy",
            "banana smoothie recipe",
        ]
    )
    anchor, near, far = batch.vectors
    assert _cosine(anchor, near) > _cosine(anchor, far)


async def test_case_and_whitespace_normalized() -> None:
    embedder = HashingEmbedder(dimensions=256)
    batch = await embedder.embed_batch(["Audit  Log\tRetention", "audit log retention"])
    assert batch.vectors[0] == batch.vectors[1]


async def test_empty_input_yields_fixed_unit_vector() -> None:
    embedder = HashingEmbedder(dimensions=16)
    batch = await embedder.embed_batch(["   "])
    (vector,) = batch.vectors
    assert vector[0] == 1.0
    assert all(v == 0.0 for v in vector[1:])


async def test_usage_counts_words_and_model_ref() -> None:
    embedder = HashingEmbedder(dimensions=32)
    batch = await embedder.embed_batch(["one two three", "four"])
    assert batch.usage.prompt_tokens == 4
    assert batch.usage.completion_tokens == 0
    assert str(batch.model) == "hash/ngram"


def test_rejects_non_positive_dimensions() -> None:
    with pytest.raises(InvalidInputError):
        HashingEmbedder(dimensions=0)
