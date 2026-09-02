"""Pure retrieval metrics: recall@k, MRR, precision@k, hit rate@k, nDCG@k."""

from __future__ import annotations

from math import log2

import pytest

from app.modules.evaluation.domain.metrics import (
    aggregate,
    hit_rate_at_k,
    mrr,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
)
from app.shared.domain.errors import InvalidInputError

RELEVANT = frozenset({"a.pdf", "b.pdf"})


def _dcg(*ranks: int) -> float:
    """Discounted gain contributed by relevant ids at these 1-based ranks."""
    return sum(1.0 / log2(rank + 1) for rank in ranks)


class TestRecallAtK:
    def test_perfect_recall(self) -> None:
        assert recall_at_k(RELEVANT, ["a.pdf", "b.pdf", "x"], k=3) == 1.0

    def test_zero_recall(self) -> None:
        assert recall_at_k(RELEVANT, ["x", "y", "z"], k=3) == 0.0

    def test_partial_recall(self) -> None:
        assert recall_at_k(RELEVANT, ["a.pdf", "x", "y"], k=3) == 0.5

    def test_empty_retrieved_scores_zero(self) -> None:
        assert recall_at_k(RELEVANT, [], k=5) == 0.0

    def test_k_larger_than_retrieved_list(self) -> None:
        assert recall_at_k(RELEVANT, ["a.pdf"], k=100) == 0.5

    def test_k_cuts_off_later_hits(self) -> None:
        assert recall_at_k(RELEVANT, ["x", "y", "a.pdf"], k=2) == 0.0

    def test_duplicates_count_once(self) -> None:
        assert recall_at_k(RELEVANT, ["a.pdf", "a.pdf", "a.pdf"], k=3) == 0.5

    def test_non_positive_k_rejected(self) -> None:
        with pytest.raises(InvalidInputError):
            recall_at_k(RELEVANT, ["a.pdf"], k=0)

    def test_empty_relevant_rejected(self) -> None:
        with pytest.raises(InvalidInputError):
            recall_at_k(frozenset(), ["a.pdf"], k=1)


class TestMRR:
    def test_first_position(self) -> None:
        assert mrr(RELEVANT, ["a.pdf", "x", "y"]) == 1.0

    def test_third_position(self) -> None:
        assert mrr(RELEVANT, ["x", "y", "b.pdf"]) == pytest.approx(1 / 3)

    def test_only_first_hit_counts(self) -> None:
        assert mrr(RELEVANT, ["x", "a.pdf", "b.pdf"]) == pytest.approx(1 / 2)

    def test_no_hit_is_zero(self) -> None:
        assert mrr(RELEVANT, ["x", "y"]) == 0.0

    def test_empty_retrieved_is_zero(self) -> None:
        assert mrr(RELEVANT, []) == 0.0

    def test_empty_relevant_rejected(self) -> None:
        with pytest.raises(InvalidInputError):
            mrr(frozenset(), ["a.pdf"])


class TestPrecisionAtK:
    def test_perfect_precision(self) -> None:
        assert precision_at_k(RELEVANT, ["a.pdf", "b.pdf"], k=2) == 1.0

    def test_zero_precision(self) -> None:
        assert precision_at_k(RELEVANT, ["x", "y", "z"], k=3) == 0.0

    def test_partial_precision(self) -> None:
        assert precision_at_k(RELEVANT, ["a.pdf", "x", "y"], k=3) == pytest.approx(1 / 3)

    def test_empty_retrieved_scores_zero(self) -> None:
        assert precision_at_k(RELEVANT, [], k=5) == 0.0

    def test_denominator_is_capped_at_retrieved_length(self) -> None:
        # Only one chunk was returned, so k=100 must not punish 99 empty slots.
        assert precision_at_k(RELEVANT, ["a.pdf"], k=100) == 1.0

    def test_k_cuts_off_later_hits(self) -> None:
        assert precision_at_k(RELEVANT, ["x", "y", "a.pdf"], k=2) == 0.0

    def test_duplicate_relevant_ids_count_per_position(self) -> None:
        # Deliberately unlike recall: both slots held a useful chunk.
        assert precision_at_k(RELEVANT, ["a.pdf", "a.pdf"], k=2) == 1.0

    def test_miss_markers_consume_rank_slots(self) -> None:
        # The __miss_N ids the use case assigns are unique and never relevant.
        assert precision_at_k(RELEVANT, ["a.pdf", "__miss_1", "__miss_2"], k=3) == pytest.approx(
            1 / 3
        )

    def test_non_positive_k_rejected(self) -> None:
        with pytest.raises(InvalidInputError):
            precision_at_k(RELEVANT, ["a.pdf"], k=0)

    def test_empty_relevant_rejected(self) -> None:
        with pytest.raises(InvalidInputError):
            precision_at_k(frozenset(), ["a.pdf"], k=1)


class TestHitRateAtK:
    def test_hit_at_first_position(self) -> None:
        assert hit_rate_at_k(RELEVANT, ["a.pdf", "x"], k=2) == 1.0

    def test_hit_at_last_position_in_window(self) -> None:
        assert hit_rate_at_k(RELEVANT, ["x", "y", "b.pdf"], k=3) == 1.0

    def test_no_hit_is_zero(self) -> None:
        assert hit_rate_at_k(RELEVANT, ["x", "y"], k=2) == 0.0

    def test_empty_retrieved_scores_zero(self) -> None:
        assert hit_rate_at_k(RELEVANT, [], k=5) == 0.0

    def test_k_cuts_off_later_hits(self) -> None:
        assert hit_rate_at_k(RELEVANT, ["x", "y", "a.pdf"], k=2) == 0.0

    def test_partial_coverage_still_scores_one(self) -> None:
        # The permissive counterpart to recall: one of two source files is a hit.
        assert hit_rate_at_k(RELEVANT, ["a.pdf", "x"], k=2) == 1.0
        assert recall_at_k(RELEVANT, ["a.pdf", "x"], k=2) == 0.5

    def test_k_larger_than_retrieved_list(self) -> None:
        assert hit_rate_at_k(RELEVANT, ["a.pdf"], k=100) == 1.0

    def test_non_positive_k_rejected(self) -> None:
        with pytest.raises(InvalidInputError):
            hit_rate_at_k(RELEVANT, ["a.pdf"], k=-1)

    def test_empty_relevant_rejected(self) -> None:
        with pytest.raises(InvalidInputError):
            hit_rate_at_k(frozenset(), ["a.pdf"], k=1)


class TestNdcgAtK:
    def test_perfect_ranking_scores_one(self) -> None:
        assert ndcg_at_k(RELEVANT, ["a.pdf", "b.pdf", "x"], k=3) == 1.0

    def test_worst_ranking_scores_zero(self) -> None:
        assert ndcg_at_k(RELEVANT, ["x", "y", "z"], k=3) == 0.0

    def test_empty_retrieved_scores_zero(self) -> None:
        assert ndcg_at_k(RELEVANT, [], k=5) == 0.0

    def test_demoted_hits_score_below_perfect(self) -> None:
        expected = _dcg(2, 3) / _dcg(1, 2)
        assert ndcg_at_k(RELEVANT, ["x", "a.pdf", "b.pdf"], k=3) == pytest.approx(expected)

    def test_single_hit_discounted_by_rank(self) -> None:
        expected = _dcg(3) / _dcg(1, 2)
        assert ndcg_at_k(RELEVANT, ["x", "y", "b.pdf"], k=3) == pytest.approx(expected)

    def test_earlier_rank_scores_higher(self) -> None:
        early = ndcg_at_k(RELEVANT, ["a.pdf", "x", "y"], k=3)
        late = ndcg_at_k(RELEVANT, ["x", "y", "a.pdf"], k=3)
        assert early > late

    def test_duplicate_relevant_id_credited_once_at_best_position(self) -> None:
        # The repeat at rank 2 is not new evidence, so this must score exactly
        # the same as a run that wasted rank 2 on an irrelevant chunk.
        with_duplicate = ndcg_at_k(RELEVANT, ["a.pdf", "a.pdf", "b.pdf"], k=3)
        with_miss = ndcg_at_k(RELEVANT, ["a.pdf", "__miss_1", "b.pdf"], k=3)
        assert with_duplicate == pytest.approx(with_miss)
        assert with_duplicate == pytest.approx(_dcg(1, 3) / _dcg(1, 2))

    def test_repeating_one_source_cannot_reach_perfect(self) -> None:
        assert ndcg_at_k(RELEVANT, ["a.pdf", "a.pdf", "a.pdf"], k=3) == pytest.approx(
            _dcg(1) / _dcg(1, 2)
        )

    def test_ideal_ranking_is_truncated_by_k(self) -> None:
        # With k=1 only one relevant id can possibly be shown, so a single hit
        # at rank 1 is a perfect score despite the second source file missing.
        assert ndcg_at_k(RELEVANT, ["a.pdf", "b.pdf"], k=1) == 1.0

    def test_k_larger_than_retrieved_list(self) -> None:
        assert ndcg_at_k(RELEVANT, ["a.pdf"], k=100) == pytest.approx(_dcg(1) / _dcg(1, 2))

    def test_k_cuts_off_later_hits(self) -> None:
        assert ndcg_at_k(RELEVANT, ["x", "y", "a.pdf"], k=2) == 0.0

    def test_miss_markers_are_never_relevant(self) -> None:
        assert ndcg_at_k(RELEVANT, ["__miss_0", "__miss_1"], k=2) == 0.0

    def test_idcg_is_never_zero_so_no_division_guard_is_needed(self) -> None:
        # The validation guards make IDCG structurally positive: the smallest
        # legal inputs (k=1, one relevant id) still leave one ideal position,
        # so a 0.0 score always means "found nothing", never "undefined".
        assert ndcg_at_k(frozenset({"a.pdf"}), [], k=1) == 0.0
        assert ndcg_at_k(frozenset({"a.pdf"}), ["a.pdf"], k=1) == 1.0

    def test_non_positive_k_rejected(self) -> None:
        with pytest.raises(InvalidInputError):
            ndcg_at_k(RELEVANT, ["a.pdf"], k=0)

    def test_empty_relevant_rejected(self) -> None:
        with pytest.raises(InvalidInputError):
            ndcg_at_k(frozenset(), ["a.pdf"], k=1)


class TestAggregate:
    def test_means_and_count(self) -> None:
        results = [
            (frozenset({"a"}), ("a", "x")),  # recall 1.0, rr 1.0
            (frozenset({"a"}), ("x", "a")),  # recall 1.0, rr 0.5
            (frozenset({"a"}), ("x", "y")),  # recall 0.0, rr 0.0
        ]
        scores = aggregate(results, k=2)
        assert scores.recall_at_k == pytest.approx(2 / 3)
        assert scores.mrr == pytest.approx(0.5)
        assert scores.k == 2
        assert scores.examples == 3

    def test_mrr_respects_k_horizon(self) -> None:
        # The hit sits at rank 3; with k=2 it must count for neither metric.
        scores = aggregate([(frozenset({"a"}), ("x", "y", "a"))], k=2)
        assert scores.recall_at_k == 0.0
        assert scores.mrr == 0.0

    def test_new_metrics_are_averaged_too(self) -> None:
        results = [
            (frozenset({"a"}), ("a", "x")),  # precision 0.5, hit 1.0, ndcg 1.0
            (frozenset({"a"}), ("x", "y")),  # precision 0.0, hit 0.0, ndcg 0.0
        ]
        scores = aggregate(results, k=2)
        assert scores.precision_at_k == pytest.approx(0.25)
        assert scores.hit_rate_at_k == pytest.approx(0.5)
        assert scores.ndcg_at_k == pytest.approx(0.5)

    def test_new_metrics_respect_k_horizon(self) -> None:
        scores = aggregate([(frozenset({"a"}), ("x", "y", "a"))], k=2)
        assert scores.precision_at_k == 0.0
        assert scores.hit_rate_at_k == 0.0
        assert scores.ndcg_at_k == 0.0

    def test_perfect_run_scores_one_across_the_board(self) -> None:
        scores = aggregate([(frozenset({"a", "b"}), ("a", "b"))], k=2)
        assert scores.recall_at_k == 1.0
        assert scores.mrr == 1.0
        assert scores.precision_at_k == 1.0
        assert scores.hit_rate_at_k == 1.0
        assert scores.ndcg_at_k == 1.0

    def test_zero_examples_rejected(self) -> None:
        with pytest.raises(InvalidInputError):
            aggregate([], k=5)

    def test_non_positive_k_rejected(self) -> None:
        with pytest.raises(InvalidInputError):
            aggregate([(frozenset({"a"}), ("a",))], k=0)
