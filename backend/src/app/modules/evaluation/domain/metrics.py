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

The retrieved sequence is *positional*: the caller (``_retrieved_ids`` in the
application layer) maps every non-relevant chunk to a unique ``__miss_N``
marker so a bad chunk still consumes a rank slot, while a relevant chunk keeps
its source filename — so the same relevant id can legitimately repeat. Each
metric below states how it treats that repetition, because the honest answer
differs per metric: precision asks "how much of the page was worth reading"
(positions), recall/nDCG ask "how much of the required evidence did we surface"
(unique ids).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from math import log2

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


def precision_at_k(relevant: frozenset[str], retrieved: Sequence[str], k: int) -> float:
    """Fraction of the top-``k`` *positions* that hold a relevant id.

    Unlike recall, this counts positions rather than unique ids: two chunks
    from the same relevant source file are two useful rank slots even though
    they carry the same id, and the ``__miss_N`` markers the caller assigns to
    non-relevant chunks are unique by construction, so position counting is the
    only reading that answers "how much of what we showed was worth reading".

    The denominator is ``min(k, len(retrieved))`` — scoring a retriever that
    returned three chunks against a k of ten would penalise it for slots it was
    never given. An empty ``retrieved`` scores 0.0 rather than dividing by zero.
    """
    if k <= 0:
        raise InvalidInputError(f"k must be positive, got {k}")
    if not relevant:
        raise InvalidInputError("relevant set must not be empty")
    window = retrieved[:k]
    if not window:
        return 0.0
    hits = sum(1 for item in window if item in relevant)
    return hits / len(window)


def hit_rate_at_k(relevant: frozenset[str], retrieved: Sequence[str], k: int) -> float:
    """1.0 when any relevant id appears in the top ``k``, else 0.0.

    The permissive counterpart to recall@k: on cross-document questions recall
    demands every source file, while hit rate only asks whether the retriever
    got a foothold at all. Reported together they separate "found nothing" from
    "found part of the story" — a distinction a mean recall alone hides.
    """
    if k <= 0:
        raise InvalidInputError(f"k must be positive, got {k}")
    if not relevant:
        raise InvalidInputError("relevant set must not be empty")
    return 1.0 if relevant.intersection(retrieved[:k]) else 0.0


def ndcg_at_k(relevant: frozenset[str], retrieved: Sequence[str], k: int) -> float:
    """Binary-gain nDCG@k: rank-discounted credit for the evidence found.

    ``DCG = sum(rel_i / log2(i + 1))`` over 1-based positions ``i`` in the top
    ``k``; ``IDCG`` is the same sum for the ideal ordering, which places
    ``min(len(relevant), k)`` relevant ids first. The two guards above make
    IDCG structurally positive — ``k >= 1`` and a non-empty ``relevant`` set
    force at least one ideal position — so the usual "return 0.0 when IDCG is
    0" escape hatch is unreachable here and is deliberately not written as a
    branch; a zero score instead comes from a zero DCG, which is what "the
    top-k held none of the required evidence" should mean.

    Duplicates count *once*, at their best (earliest) position: a second chunk
    from an already-credited source file is not new evidence, so crediting it
    again would let a retriever inflate nDCG by returning the same document
    repeatedly. This matches recall@k's unique-id reading; ``precision_at_k``
    deliberately differs.
    """
    if k <= 0:
        raise InvalidInputError(f"k must be positive, got {k}")
    if not relevant:
        raise InvalidInputError("relevant set must not be empty")
    seen: set[str] = set()
    dcg = 0.0
    for rank, item in enumerate(retrieved[:k], start=1):
        if item in relevant and item not in seen:
            seen.add(item)
            dcg += 1.0 / log2(rank + 1)
    ideal_hits = min(len(relevant), k)
    idcg = sum(1.0 / log2(rank + 1) for rank in range(1, ideal_hits + 1))
    return dcg / idcg


def aggregate(
    results: Iterable[tuple[frozenset[str], Sequence[str]]],
    *,
    k: int,
) -> RetrievalScores:
    """Mean recall@k, MRR, precision@k, hit rate@k and nDCG@k over pairs.

    All five read the same ``(relevant, retrieved)`` pairs at one shared ``k``,
    so a run reports a single coherent horizon rather than five metrics that
    silently disagree about how deep the retriever was allowed to go.

    Raises :class:`InvalidInputError` for zero examples — an empty eval run
    reporting a perfect (or any) score would be a lie.
    """
    recalls: list[float] = []
    reciprocal_ranks: list[float] = []
    precisions: list[float] = []
    hit_rates: list[float] = []
    ndcgs: list[float] = []
    for relevant, retrieved in results:
        recalls.append(recall_at_k(relevant, retrieved, k))
        reciprocal_ranks.append(mrr(relevant, retrieved[:k]))
        precisions.append(precision_at_k(relevant, retrieved, k))
        hit_rates.append(hit_rate_at_k(relevant, retrieved, k))
        ndcgs.append(ndcg_at_k(relevant, retrieved, k))
    if not recalls:
        raise InvalidInputError("cannot aggregate metrics over zero examples")
    count = len(recalls)
    return RetrievalScores(
        recall_at_k=sum(recalls) / count,
        mrr=sum(reciprocal_ranks) / count,
        k=k,
        examples=count,
        precision_at_k=sum(precisions) / count,
        hit_rate_at_k=sum(hit_rates) / count,
        ndcg_at_k=sum(ndcgs) / count,
    )
