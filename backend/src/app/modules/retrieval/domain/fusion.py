"""Reciprocal Rank Fusion — the fusion step of hybrid retrieval (ADR: hand-rolled,
no framework, because this is exactly the part worth showing).

Dense (pgvector cosine) and lexical (Postgres FTS) scores live on incompatible
scales, so hybrid search cannot simply add them. RRF sidesteps score calibration
entirely by fusing on *ranks*: a chunk at rank ``r`` in one arm contributes

    1 / (k + r)

and its fused score is the sum of contributions over every arm that returned it.
Appearing in both arms therefore compounds, which is the property that makes
hybrid search beat either arm alone.

The constant ``k`` dampens the gap between adjacent ranks: with ``k = 0`` rank 1
would score twice rank 2; with ``k = 60`` (the value from Cormack, Clarke &
Buettcher's original RRF paper, and still the industry default) the top ranks
dominate far less, so agreement between arms outweighs a single arm's top hit.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from app.modules.retrieval.domain.entities import ScoredChunk

if TYPE_CHECKING:
    from collections.abc import Sequence

DEFAULT_RRF_K = 60

_DENSE_ARM = 0
_LEXICAL_ARM = 1


@dataclass(frozen=True, slots=True)
class FusedCandidate:
    """A deduplicated chunk after RRF, carrying its full per-arm provenance.

    ``dense_rank`` / ``lexical_rank`` are 1-based positions in the respective
    arm's ranking, ``None`` when the arm did not return the chunk. Keeping both
    ranks (instead of only the fused score) is what lets the search endpoint and
    the tracer show *why* a chunk won.
    """

    chunk_id: UUID
    document_id: UUID
    seq: int
    text: str
    filename: str
    heading_path: tuple[str, ...]
    fused_score: float
    dense_rank: int | None
    lexical_rank: int | None


def reciprocal_rank_fusion(
    rankings: Sequence[Sequence[ScoredChunk]],
    *,
    k: int = DEFAULT_RRF_K,
) -> list[FusedCandidate]:
    """Fuse per-arm rankings into one list ordered by summed ``1 / (k + rank)``.

    By convention ``rankings[0]`` is the dense arm and ``rankings[1]`` the
    lexical arm — that positional convention is what fills ``dense_rank`` and
    ``lexical_rank``. Extra arms still contribute to the fused score.

    Guarantees:
    - one candidate per ``chunk_id`` (chunk fields taken from its first
      occurrence; a repeat inside a single arm is counted once, at its best rank)
    - deterministic order: fused score descending, then ``chunk_id`` ascending
      as a total tie-break, so equal scores never depend on input order.
    """
    if k <= 0:
        msg = f"RRF constant k must be positive, got {k}"
        raise ValueError(msg)

    fused_scores: dict[UUID, float] = defaultdict(float)
    first_seen: dict[UUID, ScoredChunk] = {}
    arm_ranks: dict[UUID, dict[int, int]] = defaultdict(dict)

    for arm_index, arm in enumerate(rankings):
        seen_in_arm: set[UUID] = set()
        rank = 0
        for chunk in arm:
            if chunk.chunk_id in seen_in_arm:
                continue
            seen_in_arm.add(chunk.chunk_id)
            rank += 1
            fused_scores[chunk.chunk_id] += 1.0 / (k + rank)
            arm_ranks[chunk.chunk_id][arm_index] = rank
            first_seen.setdefault(chunk.chunk_id, chunk)

    candidates = [
        FusedCandidate(
            chunk_id=chunk.chunk_id,
            document_id=chunk.document_id,
            seq=chunk.seq,
            text=chunk.text,
            filename=chunk.filename,
            heading_path=chunk.heading_path,
            fused_score=fused_scores[chunk.chunk_id],
            dense_rank=arm_ranks[chunk.chunk_id].get(_DENSE_ARM),
            lexical_rank=arm_ranks[chunk.chunk_id].get(_LEXICAL_ARM),
        )
        for chunk in first_seen.values()
    ]
    candidates.sort(key=lambda c: (-c.fused_score, c.chunk_id))
    return candidates
