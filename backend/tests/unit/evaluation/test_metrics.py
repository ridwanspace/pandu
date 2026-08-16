"""Pure retrieval metrics: recall@k, MRR, aggregation."""

from __future__ import annotations

import pytest

from app.modules.evaluation.domain.metrics import aggregate, mrr, recall_at_k
from app.shared.domain.errors import InvalidInputError

RELEVANT = frozenset({"a.pdf", "b.pdf"})


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

    def test_zero_examples_rejected(self) -> None:
        with pytest.raises(InvalidInputError):
            aggregate([], k=5)
