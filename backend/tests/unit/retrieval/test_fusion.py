"""Exhaustive tests for Reciprocal Rank Fusion (pure domain, no I/O)."""

from __future__ import annotations

from uuid import UUID

import pytest

from app.modules.retrieval.domain.entities import ScoredChunk
from app.modules.retrieval.domain.fusion import reciprocal_rank_fusion


def chunk(n: int, *, text: str | None = None) -> ScoredChunk:
    return ScoredChunk(
        chunk_id=UUID(int=n),
        document_id=UUID(int=1000 + n),
        seq=n,
        text=text if text is not None else f"chunk {n}",
        filename="doc.md",
        heading_path=("Intro",),
        score=0.5,
    )


A, B, C = chunk(1), chunk(2), chunk(3)


class TestOverlap:
    def test_chunk_in_both_arms_sums_contributions(self) -> None:
        fused = reciprocal_rank_fusion([[A, B], [B, C]], k=60)

        by_id = {c.chunk_id: c for c in fused}
        assert by_id[B.chunk_id].fused_score == pytest.approx(1 / 62 + 1 / 61)
        assert by_id[A.chunk_id].fused_score == pytest.approx(1 / 61)
        assert by_id[C.chunk_id].fused_score == pytest.approx(1 / 62)
        # agreement between arms wins over either arm's top hit
        assert [c.chunk_id for c in fused] == [B.chunk_id, A.chunk_id, C.chunk_id]

    def test_per_arm_ranks_are_one_based_positions(self) -> None:
        fused = reciprocal_rank_fusion([[A, B], [B, C]])

        by_id = {c.chunk_id: c for c in fused}
        assert (by_id[A.chunk_id].dense_rank, by_id[A.chunk_id].lexical_rank) == (1, None)
        assert (by_id[B.chunk_id].dense_rank, by_id[B.chunk_id].lexical_rank) == (2, 1)
        assert (by_id[C.chunk_id].dense_rank, by_id[C.chunk_id].lexical_rank) == (None, 2)

    def test_chunk_fields_are_preserved(self) -> None:
        fused = reciprocal_rank_fusion([[A], []])

        (candidate,) = fused
        assert candidate.chunk_id == A.chunk_id
        assert candidate.document_id == A.document_id
        assert candidate.seq == A.seq
        assert candidate.text == A.text
        assert candidate.filename == A.filename
        assert candidate.heading_path == A.heading_path


class TestSingleArm:
    def test_dense_only_hits_have_no_lexical_rank(self) -> None:
        fused = reciprocal_rank_fusion([[A, B], []], k=60)

        assert [c.chunk_id for c in fused] == [A.chunk_id, B.chunk_id]
        assert all(c.lexical_rank is None for c in fused)
        assert [c.dense_rank for c in fused] == [1, 2]
        assert [c.fused_score for c in fused] == pytest.approx([1 / 61, 1 / 62])

    def test_lexical_only_hits_have_no_dense_rank(self) -> None:
        fused = reciprocal_rank_fusion([[], [A]], k=60)

        (candidate,) = fused
        assert candidate.dense_rank is None
        assert candidate.lexical_rank == 1
        assert candidate.fused_score == pytest.approx(1 / 61)


class TestKSensitivity:
    def test_small_k_favours_top_ranks_large_k_favours_agreement(self) -> None:
        a, b = chunk(10), chunk(11)
        fillers_dense = [chunk(20), chunk(21)]
        fillers_lexical = [chunk(30), chunk(31), chunk(32)]
        dense = [a, *fillers_dense, b]  # a at rank 1, b at rank 4
        lexical = [*fillers_lexical, b]  # b at rank 4

        def positions(k: int) -> tuple[int, int]:
            order = [c.chunk_id for c in reciprocal_rank_fusion([dense, lexical], k=k)]
            return order.index(a.chunk_id), order.index(b.chunk_id)

        # k=1: a = 1/2 beats b = 2/5 — a single top hit dominates
        pos_a, pos_b = positions(1)
        assert pos_a < pos_b
        # k=60: b = 2/64 beats a = 1/61 — appearing in both arms dominates
        pos_a, pos_b = positions(60)
        assert pos_b < pos_a

    def test_invalid_k_rejected(self) -> None:
        with pytest.raises(ValueError, match="must be positive"):
            reciprocal_rank_fusion([[A]], k=0)
        with pytest.raises(ValueError, match="must be positive"):
            reciprocal_rank_fusion([[A]], k=-5)


class TestDeterminism:
    def test_equal_scores_break_ties_by_chunk_id(self) -> None:
        # A and B each rank 1 of exactly one arm: identical fused scores.
        fused = reciprocal_rank_fusion([[A], [B]])
        assert [c.chunk_id for c in fused] == [A.chunk_id, B.chunk_id]

        # Swapping which arm produced which chunk must not change the order.
        fused = reciprocal_rank_fusion([[B], [A]])
        assert [c.chunk_id for c in fused] == [A.chunk_id, B.chunk_id]

    def test_repeated_calls_are_identical(self) -> None:
        rankings = [[A, B, C], [C, B]]
        assert reciprocal_rank_fusion(rankings) == reciprocal_rank_fusion(rankings)


class TestDedupe:
    def test_duplicate_within_one_arm_counted_once_at_best_rank(self) -> None:
        fused = reciprocal_rank_fusion([[A, A, B], []], k=60)

        by_id = {c.chunk_id: c for c in fused}
        assert len(fused) == 2
        assert by_id[A.chunk_id].fused_score == pytest.approx(1 / 61)
        assert by_id[A.chunk_id].dense_rank == 1
        # the duplicate does not shift later ranks
        assert by_id[B.chunk_id].dense_rank == 2

    def test_across_arms_yields_one_candidate_with_first_seen_fields(self) -> None:
        dense_version = chunk(7, text="dense text")
        lexical_version = chunk(7, text="lexical text")

        fused = reciprocal_rank_fusion([[dense_version], [lexical_version]])

        (candidate,) = fused
        assert candidate.text == "dense text"
        assert (candidate.dense_rank, candidate.lexical_rank) == (1, 1)


class TestEmpty:
    def test_no_rankings(self) -> None:
        assert reciprocal_rank_fusion([]) == []

    def test_empty_arms(self) -> None:
        assert reciprocal_rank_fusion([[], []]) == []
