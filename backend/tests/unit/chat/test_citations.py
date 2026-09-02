"""Citation-marker extraction, filtering and validation."""

from __future__ import annotations

from uuid import uuid4

from app.modules.chat.domain.citations import (
    extract_marker_set,
    used_citations,
    validate_citations,
)
from app.modules.chat.domain.entities import Citation


def _citation(marker: int) -> Citation:
    return Citation(
        marker=marker,
        chunk_id=uuid4(),
        document_id=uuid4(),
        filename=f"doc{marker}.md",
        heading_path=(),
        snippet="snippet",
        score=0.5,
    )


class TestExtractMarkerSet:
    def test_finds_all_numeric_markers(self) -> None:
        assert extract_marker_set("Install uv [1], then sync [2]. See also [1].") == {1, 2}

    def test_ignores_non_numeric_brackets_and_empty_text(self) -> None:
        assert extract_marker_set("no markers [x] [ 1 ] []") == set()
        assert extract_marker_set("") == set()

    def test_multi_digit_markers(self) -> None:
        assert extract_marker_set("deep cut [12]") == {12}


class TestUsedCitations:
    def test_filters_to_cited_preserving_order(self) -> None:
        citations = (_citation(1), _citation(2), _citation(3))
        used = used_citations(citations, "claim [3] and claim [1]")
        assert [c.marker for c in used] == [1, 3]

    def test_no_markers_means_no_citations(self) -> None:
        assert used_citations((_citation(1),), "an uncited answer") == ()

    def test_hallucinated_marker_is_still_dropped_from_the_filter(self) -> None:
        assert used_citations((_citation(1),), "claim [9]") == ()


class TestValidateCitations:
    def test_all_markers_valid(self) -> None:
        citations = (_citation(1), _citation(2))
        report = validate_citations(citations, "claim [2] and claim [1]")

        assert [c.marker for c in report.cited] == [1, 2]
        assert report.invalid_markers == ()
        assert report.uncited_markers == ()
        assert report.is_valid
        assert report.validity == 1.0

    def test_out_of_range_marker_is_reported_not_dropped(self) -> None:
        report = validate_citations((_citation(1), _citation(2)), "grounded [1], invented [9]")

        assert [c.marker for c in report.cited] == [1]
        assert report.invalid_markers == (9,)
        assert report.uncited_markers == (2,)
        assert not report.is_valid
        assert report.validity == 0.5

    def test_zero_marker_is_invalid(self) -> None:
        report = validate_citations((_citation(1),), "claim [0]")

        assert report.cited == ()
        assert report.invalid_markers == (0,)
        assert not report.is_valid
        assert report.validity == 0.0

    def test_negative_looking_marker_parses_as_positive_and_is_invalid(self) -> None:
        # The marker regex never matches a minus sign, so "[-3]" yields nothing
        # and "[3]" inside it is not a match either — no markers at all.
        report = validate_citations((_citation(1),), "claim [-3]")

        assert report.invalid_markers == ()
        assert report.is_valid
        assert report.validity == 1.0

    def test_answer_citing_nothing_is_vacuously_valid(self) -> None:
        report = validate_citations(
            (_citation(1), _citation(2)), "The context does not cover this."
        )

        assert report.cited == ()
        assert report.invalid_markers == ()
        assert report.uncited_markers == (1, 2)
        assert report.is_valid
        assert report.validity == 1.0

    def test_no_citations_and_no_markers_is_valid(self) -> None:
        report = validate_citations((), "nothing retrieved, nothing cited")

        assert report.cited == ()
        assert report.invalid_markers == ()
        assert report.uncited_markers == ()
        assert report.validity == 1.0

    def test_duplicate_markers_counted_once(self) -> None:
        report = validate_citations((_citation(1),), "[9] and [9] and [9] but also [1]")

        assert [c.marker for c in report.cited] == [1]
        assert report.invalid_markers == (9,)
        assert report.validity == 0.5

    def test_invalid_markers_are_sorted_and_deduped(self) -> None:
        report = validate_citations((_citation(1),), "[12] [3] [12] [1] [7]")

        assert report.invalid_markers == (3, 7, 12)
        assert report.uncited_markers == ()
        assert report.validity == 0.25

    def test_uncited_retrieved_sources_are_reported(self) -> None:
        report = validate_citations((_citation(1), _citation(2), _citation(3)), "only [2]")

        assert [c.marker for c in report.cited] == [2]
        assert report.uncited_markers == (1, 3)
        assert report.is_valid
        assert report.validity == 1.0
