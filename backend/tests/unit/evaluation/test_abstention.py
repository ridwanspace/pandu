"""Abstention detection and scoring — pure, deterministic, no LLM."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.modules.evaluation.domain.abstention import (
    ABSTENTION_MARKERS,
    is_abstention,
    score_abstention,
)
from app.shared.domain.errors import InvalidInputError


class TestIsAbstention:
    def test_empty_answer_is_abstention(self) -> None:
        """No claim was asserted, so nothing can be wrong."""
        assert is_abstention("") is True

    def test_whitespace_only_is_abstention(self) -> None:
        assert is_abstention("   \n\t  ") is True

    def test_grounded_answer_is_not_abstention(self) -> None:
        answer = "AAL2 requires two distinct authentication factors [1]."
        assert is_abstention(answer) is False

    def test_refusal_phrase_detected(self) -> None:
        answer = "The provided context does not contain information about HIPAA."
        assert is_abstention(answer) is True

    def test_detection_is_case_insensitive(self) -> None:
        assert is_abstention("The Context Does Not Contain that detail.") is True

    @pytest.mark.parametrize("marker", ABSTENTION_MARKERS)
    def test_every_marker_triggers_detection(self, marker: str) -> None:
        """Each listed phrase must actually work — a dead marker is a silent hole."""
        assert is_abstention(f"Sorry, this {marker} here.") is True

    def test_answer_mentioning_topic_without_refusal(self) -> None:
        """A real answer about missing data must not read as an abstention."""
        answer = "Audit records are retained per organizational policy [1]."
        assert is_abstention(answer) is False


class TestScoreAbstention:
    def test_perfect_abstention(self) -> None:
        """Declines every negative, answers every positive."""
        scores = score_abstention([(False, True), (False, True), (True, False), (True, False)])
        assert scores.abstention_recall == 1.0
        assert scores.false_abstention_rate == 0.0
        assert scores.negatives == 2
        assert scores.positives == 2

    def test_answers_everything(self) -> None:
        """The failure mode that matters: confident answers on unanswerable questions."""
        scores = score_abstention([(False, False), (False, False), (True, False)])
        assert scores.abstention_recall == 0.0
        assert scores.false_abstention_rate == 0.0
        assert scores.negatives == 2

    def test_abstains_on_everything(self) -> None:
        """The opposite failure: useless but safe."""
        scores = score_abstention([(False, True), (True, True), (True, True)])
        assert scores.abstention_recall == 1.0
        assert scores.false_abstention_rate == 1.0

    def test_partial_scores(self) -> None:
        scores = score_abstention([(False, True), (False, False), (True, False), (True, True)])
        assert scores.abstention_recall == 0.5
        assert scores.false_abstention_rate == 0.5

    def test_no_negatives_reports_zero_with_population(self) -> None:
        """0.0 with negatives=0 is distinguishable from 0.0 with negatives>0."""
        scores = score_abstention([(True, False), (True, False)])
        assert scores.abstention_recall == 0.0
        assert scores.negatives == 0
        assert scores.positives == 2

    def test_no_positives_reports_zero_false_abstention(self) -> None:
        scores = score_abstention([(False, True)])
        assert scores.false_abstention_rate == 0.0
        assert scores.positives == 0
        assert scores.negatives == 1

    def test_zero_examples_raises(self) -> None:
        """An empty run reporting any score would be a lie."""
        with pytest.raises(InvalidInputError, match="zero examples"):
            score_abstention([])


class TestMarkersAgainstTheGoldenSet:
    """The phrase list is only as good as the wordings it actually catches.

    These two tests are the maintenance rule referenced in
    :mod:`app.modules.evaluation.domain.abstention`: they read the real golden
    file, so a negative phrased in a way the markers miss fails here instead of
    silently costing abstention recall in a scored run.
    """

    @staticmethod
    def _golden() -> list[dict[str, object]]:
        path = Path(__file__).resolve().parents[3] / "evals" / "golden" / "golden_v2.jsonl"
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]

    def test_every_negative_reference_answer_reads_as_a_refusal(self) -> None:
        missed = [
            row["id"]
            for row in self._golden()
            if not row.get("answerable", True) and not is_abstention(str(row["reference_answer"]))
        ]
        assert missed == [], f"negatives phrased outside the marker list: {missed}"

    def test_no_answerable_reference_answer_reads_as_a_refusal(self) -> None:
        """The costlier direction: a real answer misread as an abstention would
        inflate false_abstention_rate and make a healthy system look broken."""
        false_positives = [
            row["id"]
            for row in self._golden()
            if row.get("answerable", True) and is_abstention(str(row["reference_answer"]))
        ]
        assert false_positives == [], f"real answers misread as refusals: {false_positives}"
