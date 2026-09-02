"""Regression diffing — the check an aggregate threshold cannot make."""

from __future__ import annotations

import pytest

from app.modules.evaluation.domain.diffing import (
    Direction,
    classify,
    diff_runs,
)
from app.shared.domain.errors import InvalidInputError


class TestClassify:
    def test_higher_is_better_by_default(self) -> None:
        assert classify("recall_at_k", 0.80, 0.90, tolerance=1e-6) is Direction.IMPROVED
        assert classify("recall_at_k", 0.90, 0.80, tolerance=1e-6) is Direction.REGRESSED

    def test_lower_is_better_metric_inverts(self) -> None:
        """A rising false-abstention rate is a regression despite the number growing."""
        assert classify("false_abstention_rate", 0.10, 0.30, tolerance=1e-6) is Direction.REGRESSED
        assert classify("false_abstention_rate", 0.30, 0.10, tolerance=1e-6) is Direction.IMPROVED

    def test_change_within_tolerance_is_unchanged(self) -> None:
        """Float noise must not read as a regression."""
        assert classify("mrr", 0.8220000, 0.8220001, tolerance=1e-6) is Direction.UNCHANGED

    def test_change_exactly_at_tolerance_is_unchanged(self) -> None:
        """The band is inclusive: ``abs(change) <= tolerance`` is noise.

        Measured from 0.0 rather than an offset like ``0.5 + 1e-6``, which
        lands a few ULPs *above* the tolerance and would test rounding rather
        than the boundary rule.
        """
        assert classify("mrr", 0.0, 1e-6, tolerance=1e-6) is Direction.UNCHANGED

    def test_change_just_beyond_tolerance_is_a_regression(self) -> None:
        """The other side of the same boundary."""
        assert classify("mrr", 0.0, -2e-6, tolerance=1e-6) is Direction.REGRESSED


class TestDiffRuns:
    def test_detects_regression_and_improvement_together(self) -> None:
        """The exact case a flat aggregate hides: some up, some down."""
        diff = diff_runs(
            {"recall_at_k": 0.90, "mrr": 0.80, "ndcg_at_k": 0.70},
            {"recall_at_k": 0.95, "mrr": 0.60, "ndcg_at_k": 0.70},
        )
        assert diff.has_regression is True
        assert [d.name for d in diff.regressions] == ["mrr"]
        assert [d.name for d in diff.improvements] == ["recall_at_k"]

    def test_clean_run_has_no_regressions(self) -> None:
        diff = diff_runs({"recall_at_k": 0.90}, {"recall_at_k": 0.95})
        assert diff.has_regression is False

    def test_identical_runs_are_all_unchanged(self) -> None:
        diff = diff_runs({"recall_at_k": 0.9, "mrr": 0.8}, {"recall_at_k": 0.9, "mrr": 0.8})
        assert diff.regressions == ()
        assert diff.improvements == ()
        assert all(d.direction is Direction.UNCHANGED for d in diff.deltas)

    def test_delta_preserves_sign(self) -> None:
        (delta,) = diff_runs({"mrr": 0.80}, {"mrr": 0.60}).deltas
        assert delta.delta == pytest.approx(-0.20)
        assert delta.baseline == 0.80
        assert delta.current == 0.60

    def test_growing_the_dataset_is_not_a_regression(self) -> None:
        """examples/negatives/positives record run shape, not quality."""
        diff = diff_runs(
            {"recall_at_k": 0.9, "examples": 15.0, "negatives": 0.0},
            {"recall_at_k": 0.9, "examples": 20.0, "negatives": 5.0},
        )
        assert diff.has_regression is False
        assert [d.name for d in diff.deltas] == ["recall_at_k"]

    def test_new_and_dropped_metrics_are_surfaced(self) -> None:
        """A changed metric set changes what 'good' means — never silent."""
        diff = diff_runs(
            {"recall_at_k": 0.9, "old_metric": 1.0},
            {"recall_at_k": 0.9, "ndcg_at_k": 0.7},
        )
        assert diff.added == ("ndcg_at_k",)
        assert diff.removed == ("old_metric",)

    def test_bookkeeping_fields_are_not_reported_as_added(self) -> None:
        diff = diff_runs({"recall_at_k": 0.9}, {"recall_at_k": 0.9, "examples": 20.0})
        assert diff.added == ()

    def test_deltas_are_sorted_by_name(self) -> None:
        """Stable ordering keeps CI logs diffable."""
        diff = diff_runs(
            {"z_metric": 0.1, "a_metric": 0.2, "m_metric": 0.3},
            {"z_metric": 0.1, "a_metric": 0.2, "m_metric": 0.3},
        )
        assert [d.name for d in diff.deltas] == ["a_metric", "m_metric", "z_metric"]

    def test_no_overlapping_metrics_yields_empty_deltas(self) -> None:
        diff = diff_runs({"a": 1.0}, {"b": 2.0})
        assert diff.deltas == ()
        assert diff.added == ("b",)
        assert diff.removed == ("a",)

    def test_non_positive_tolerance_rejected(self) -> None:
        with pytest.raises(InvalidInputError, match="tolerance must be positive"):
            diff_runs({"a": 1.0}, {"a": 1.0}, tolerance=0.0)

    def test_custom_tolerance_widens_the_noise_band(self) -> None:
        diff = diff_runs({"mrr": 0.80}, {"mrr": 0.79}, tolerance=0.05)
        assert diff.has_regression is False
