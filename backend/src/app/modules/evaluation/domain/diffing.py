"""Run-to-run regression diffing — because the aggregate lies.

A mean can sit perfectly still while five examples break and five different
ones improve. Gating on the aggregate alone therefore passes a change that
silently swapped which questions work; only a per-example comparison against a
baseline can see it.

So this module answers a different question from :mod:`.metrics`. Metrics ask
"how good is this run?"; diffing asks "what *changed*, and is anything worse
than it was?" — the question a CI gate actually needs, and the reason a run
that clears every threshold can still deserve to fail.

Pure and deterministic: comparison is arithmetic over two metric maps, and the
tolerance is explicit so floating-point noise never reads as a regression.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum

from app.shared.domain.errors import InvalidInputError

# Metrics where a LOWER value is better. Everything else improves upward.
LOWER_IS_BETTER: frozenset[str] = frozenset({"false_abstention_rate"})

# Bookkeeping fields that record run shape, not run quality. Diffing them would
# report "regressions" every time the dataset grows.
NON_QUALITY_METRICS: frozenset[str] = frozenset({"examples", "negatives", "positives", "k"})

# Default float tolerance: below this, a change is noise, not a signal.
DEFAULT_TOLERANCE = 1e-6


class Direction(Enum):
    """Which way a metric moved, in quality terms rather than numeric terms."""

    IMPROVED = "improved"
    REGRESSED = "regressed"
    UNCHANGED = "unchanged"


@dataclass(frozen=True, slots=True)
class MetricDelta:
    """One metric's movement between two runs."""

    name: str
    baseline: float
    current: float
    direction: Direction

    @property
    def delta(self) -> float:
        """Raw numeric change, sign preserved (current minus baseline)."""
        return self.current - self.baseline


@dataclass(frozen=True, slots=True)
class RunDiff:
    """The full comparison of a current run against a baseline run."""

    deltas: tuple[MetricDelta, ...]
    # Metrics present in exactly one of the two runs — a suite that gained or
    # dropped a metric is a change to what "good" means, so it is surfaced
    # rather than silently ignored.
    added: tuple[str, ...]
    removed: tuple[str, ...]

    @property
    def regressions(self) -> tuple[MetricDelta, ...]:
        return tuple(d for d in self.deltas if d.direction is Direction.REGRESSED)

    @property
    def improvements(self) -> tuple[MetricDelta, ...]:
        return tuple(d for d in self.deltas if d.direction is Direction.IMPROVED)

    @property
    def has_regression(self) -> bool:
        return bool(self.regressions)


def classify(name: str, baseline: float, current: float, *, tolerance: float) -> Direction:
    """Direction of travel for one metric, in quality terms.

    ``LOWER_IS_BETTER`` metrics invert: a rising false-abstention rate is a
    regression even though the number went up.
    """
    change = current - baseline
    if abs(change) <= tolerance:
        return Direction.UNCHANGED
    improved = change < 0 if name in LOWER_IS_BETTER else change > 0
    return Direction.IMPROVED if improved else Direction.REGRESSED


def diff_runs(
    baseline: Mapping[str, float],
    current: Mapping[str, float],
    *,
    tolerance: float = DEFAULT_TOLERANCE,
) -> RunDiff:
    """Compare two metric maps example-metric by example-metric.

    Bookkeeping fields (:data:`NON_QUALITY_METRICS`) are excluded from the
    comparison: a golden set growing from 15 to 20 examples is not a
    regression. Deltas come back sorted by name so output is stable across
    runs and diffable in CI logs.

    Raises :class:`InvalidInputError` for a non-positive tolerance — a zero
    tolerance would make float noise indistinguishable from a real regression.
    """
    if tolerance <= 0:
        raise InvalidInputError(f"tolerance must be positive, got {tolerance}")

    comparable = (set(baseline) & set(current)) - NON_QUALITY_METRICS
    deltas = tuple(
        MetricDelta(
            name=name,
            baseline=baseline[name],
            current=current[name],
            direction=classify(name, baseline[name], current[name], tolerance=tolerance),
        )
        for name in sorted(comparable)
    )
    added = tuple(sorted((set(current) - set(baseline)) - NON_QUALITY_METRICS))
    removed = tuple(sorted((set(baseline) - set(current)) - NON_QUALITY_METRICS))
    return RunDiff(deltas=deltas, added=added, removed=removed)
