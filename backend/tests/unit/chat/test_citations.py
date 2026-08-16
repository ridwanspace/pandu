"""Citation-marker extraction and filtering."""

from __future__ import annotations

from uuid import uuid4

from app.modules.chat.domain.citations import extract_marker_set, used_citations
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
