"""Retrieval metrics — pure, deterministic, LLM-free.

Retrieval evaluation is deliberately separate from generation evaluation
(§7 of the architecture review): these functions cost nothing to run, so they
gate every eval run, while LLM-judged metrics cost tokens and run on demand.

Identity model: metrics operate on opaque string ids. For our golden set the
ids are source *filenames* (see :mod:`.matching`) — recall@k then reads as
"what fraction of the documents the answer needs did the top-k contexts
cover", and MRR as "how high did the first genuinely relevant chunk rank".
Cross-document questions make recall@k strictly harder than a hit rate: all
source files must appear in the top k for a perfect score.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from app.modules.evaluation.domain.entities import RetrievalScores
from app.shared.domain.errors import InvalidInputError


def recall_at_k(relevant: frozenset[str], retrieved: Sequence[str], k: int) -> float:
    """Fraction of relevant ids present among the first ``k`` retrieved ids.

    Duplicates in ``retrieved`` count once — a second chunk from the same
    source file adds no new evidence. ``k`` larger than ``len(retrieved)``
    simply scores what was retrieved; an empty ``retrieved`` scores 0.0.
    """
    if k <= 0:
        raise InvalidInputError(f"k must be positive, got {k}")
    if not relevant:
        raise InvalidInputError("relevant set must not be empty")
    hits = relevant.intersection(retrieved[:k])
    return len(hits) / len(relevant)


def mrr(relevant: frozenset[str], retrieved: Sequence[str]) -> float:
    """Reciprocal rank (1-based) of the first relevant id; 0.0 when none.

    ``retrieved`` is assumed to already be cut at the k under evaluation —
    the caller controls the horizon, the metric only reads order.
    """
    if not relevant:
        raise InvalidInputError("relevant set must not be empty")
    for rank, item in enumerate(retrieved, start=1):
        if item in relevant:
            return 1.0 / rank
    return 0.0


def aggregate(
    results: Iterable[tuple[frozenset[str], Sequence[str]]],
    *,
    k: int,
) -> RetrievalScores:
    """Mean recall@k and mean MRR over ``(relevant, retrieved)`` pairs.

    Raises :class:`InvalidInputError` for zero examples — an empty eval run
    reporting a perfect (or any) score would be a lie.
    """
    recalls: list[float] = []
    reciprocal_ranks: list[float] = []
    for relevant, retrieved in results:
        recalls.append(recall_at_k(relevant, retrieved, k))
        reciprocal_ranks.append(mrr(relevant, retrieved[:k]))
    if not recalls:
        raise InvalidInputError("cannot aggregate metrics over zero examples")
    count = len(recalls)
    return RetrievalScores(
        recall_at_k=sum(recalls) / count,
        mrr=sum(reciprocal_ranks) / count,
        k=k,
        examples=count,
    )
