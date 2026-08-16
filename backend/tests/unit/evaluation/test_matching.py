"""Golden-set relevance matching rules."""

from __future__ import annotations

from app.modules.evaluation.domain.matching import hint_matches, matched_source


class TestHintMatches:
    def test_case_insensitive_in_text(self) -> None:
        assert hint_matches("aal2", text="Requirements for AAL2 sessions", heading_path=())

    def test_substring_not_whole_word(self) -> None:
        assert hint_matches("multi-factor", text="(multi-factor)", heading_path=())

    def test_matches_heading_segment(self) -> None:
        assert hint_matches(
            "audit record retention",
            text="unrelated body",
            heading_path=("AU Family", "AU-11 Audit Record Retention"),
        )

    def test_no_match(self) -> None:
        assert not hint_matches("AAL3", text="about passwords", heading_path=("Intro",))


class TestMatchedSource:
    def test_wrong_filename_is_irrelevant(self) -> None:
        assert (
            matched_source(
                filename="other.pdf",
                text="AAL2 everywhere",
                heading_path=(),
                source_files=("nist-sp-800-63b.pdf",),
                source_hints=("AAL2",),
            )
            is None
        )

    def test_filename_match_without_hints_is_relevant(self) -> None:
        assert (
            matched_source(
                filename="nist-csf-2.0.pdf",
                text="anything",
                heading_path=(),
                source_files=("nist-csf-2.0.pdf", "nist-sp-800-53r5.pdf"),
            )
            == "nist-csf-2.0.pdf"
        )

    def test_hints_gate_filename_matches(self) -> None:
        common = {
            "filename": "nist-sp-800-63b.pdf",
            "heading_path": (),
            "source_files": ("nist-sp-800-63b.pdf",),
            "source_hints": ("AAL2", "reauthentication"),
        }
        assert matched_source(text="Reauthentication of the subscriber...", **common) is not None
        assert matched_source(text="entirely unrelated passage", **common) is None

    def test_any_single_hint_suffices(self) -> None:
        assert (
            matched_source(
                filename="a.pdf",
                text="mentions MFA only",
                heading_path=(),
                source_files=("a.pdf",),
                source_hints=("nowhere", "MFA"),
            )
            == "a.pdf"
        )
