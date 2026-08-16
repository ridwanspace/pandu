"""Chunker behaviour: grouping, packing, overlap, splitting, determinism."""

from __future__ import annotations

import pytest

from app.modules.documents.domain.chunking import (
    ChunkDraft,
    _pack_units,
    _pack_units_flat,
    _split_by_chars,
    chunk_blocks,
)
from app.modules.documents.domain.parser import BlockKind, ParsedBlock
from tests.unit.documents.fakes import count_words


def text_block(text: str, *path: str) -> ParsedBlock:
    return ParsedBlock(kind=BlockKind.TEXT, text=text, heading_path=tuple(path))


def chunk(
    blocks: list[ParsedBlock], *, max_tokens: int = 50, overlap_tokens: int = 0
) -> list[ChunkDraft]:
    return chunk_blocks(
        blocks,
        max_tokens=max_tokens,
        overlap_tokens=overlap_tokens,
        count_tokens=count_words,
    )


def words(n: int, prefix: str = "w") -> str:
    return " ".join(f"{prefix}{i}" for i in range(n))


class TestBasics:
    def test_empty_input_yields_no_chunks(self) -> None:
        assert chunk([]) == []

    def test_blank_and_heading_blocks_are_dropped(self) -> None:
        blocks = [
            ParsedBlock(kind=BlockKind.HEADING, text="Ignored heading", heading_path=("A",)),
            text_block("   ", "A"),
        ]
        assert chunk(blocks) == []

    def test_single_block_single_chunk_with_heading_prefix(self) -> None:
        drafts = chunk([text_block("hello world", "Guide", "Setup")])
        assert len(drafts) == 1
        assert drafts[0].text == "§ Guide > Setup\nhello world"
        assert drafts[0].heading_path == ("Guide", "Setup")
        assert drafts[0].token_count == count_words(drafts[0].text)

    def test_unheaded_block_has_no_prefix(self) -> None:
        drafts = chunk([text_block("plain paragraph")])
        assert drafts[0].text == "plain paragraph"
        assert drafts[0].heading_path == ()

    @pytest.mark.parametrize(
        ("max_tokens", "overlap_tokens"),
        [(0, 0), (-1, 0), (10, -1), (10, 10), (10, 11)],
    )
    def test_invalid_parameters_raise(self, max_tokens: int, overlap_tokens: int) -> None:
        with pytest.raises(ValueError, match="tokens"):
            chunk_blocks(
                [text_block("x")],
                max_tokens=max_tokens,
                overlap_tokens=overlap_tokens,
                count_tokens=count_words,
            )


class TestHeadingGrouping:
    def test_consecutive_blocks_under_one_heading_pack_together(self) -> None:
        drafts = chunk([text_block(words(10), "A"), text_block(words(10, "x"), "A")])
        assert len(drafts) == 1
        assert words(10) in drafts[0].text
        assert words(10, "x") in drafts[0].text

    def test_sibling_subsections_pack_under_common_prefix(self) -> None:
        drafts = chunk(
            [text_block("first part", "A", "A.1"), text_block("second part", "A", "A.2")]
        )
        assert len(drafts) == 1
        assert drafts[0].heading_path == ("A",)
        assert drafts[0].text.startswith("§ A\n")

    def test_heading_change_starts_a_new_chunk(self) -> None:
        drafts = chunk([text_block("alpha text", "A"), text_block("bravo text", "B")])
        assert len(drafts) == 2
        assert drafts[0].heading_path == ("A",)
        assert drafts[1].heading_path == ("B",)
        assert "alpha" not in drafts[1].text

    def test_unheaded_blocks_group_together(self) -> None:
        drafts = chunk([text_block("one two"), text_block("three four")])
        assert len(drafts) == 1

    def test_unheaded_then_headed_are_separate(self) -> None:
        drafts = chunk([text_block("intro text"), text_block("body text", "A")])
        assert len(drafts) == 2


class TestPacking:
    def test_window_never_exceeds_max_tokens(self) -> None:
        blocks = [text_block(words(20, f"b{i}"), "A") for i in range(5)]
        drafts = chunk(blocks, max_tokens=50)
        assert len(drafts) == 3  # 40 + 40 + 20 words of body
        for draft in drafts:
            body = draft.text.split("\n", 1)[1]
            assert count_words(body) <= 50

    def test_block_exactly_at_budget_is_never_split(self) -> None:
        # Six body words, max_tokens six: the block fits and must stay whole
        # even though the contextual heading prefix pushes the rendered text
        # above the budget (the budget governs the body).
        block = text_block("Sentence one here. Sentence two here.", "A")
        drafts = chunk([block], max_tokens=6)
        assert len(drafts) == 1
        assert "Sentence one here. Sentence two here." in drafts[0].text


class TestOverlap:
    def test_continuation_windows_repeat_trailing_sentences(self) -> None:
        p1 = "one two three four five six seven eight."
        p2 = "Alpha beta gamma. Delta echo foxtrot golf hotel."
        p3 = "nine ten eleven twelve thirteen fourteen fifteen sixteen."
        blocks = [text_block(p, "A") for p in (p1, p2, p3)]
        drafts = chunk(blocks, max_tokens=20, overlap_tokens=5)
        assert len(drafts) == 2
        assert drafts[1].text.split("\n", 1)[1].startswith("Delta echo foxtrot golf hotel.")
        # The overlap sentence appears in both chunks.
        assert "Delta echo foxtrot golf hotel." in drafts[0].text
        # But not more than fits the overlap budget.
        assert "Alpha beta gamma." not in drafts[1].text

    def test_zero_overlap_duplicates_nothing(self) -> None:
        blocks = [
            text_block("First sentence here padding words now.", "A"),
            text_block("Second sentence here padding words now.", "A"),
        ]
        drafts = chunk(blocks, max_tokens=8, overlap_tokens=0)
        assert len(drafts) == 2
        assert "First" not in drafts[1].text

    def test_overlap_is_dropped_when_it_cannot_fit_with_the_next_piece(self) -> None:
        blocks = [
            text_block("alpha beta gamma delta. one two three.", "A"),
            text_block(words(9, "n"), "A"),
        ]
        drafts = chunk(blocks, max_tokens=10, overlap_tokens=5)
        assert len(drafts) == 2
        assert "one two three." in drafts[0].text
        # Overlap (3 tokens) plus the next 9-token piece would blow the budget,
        # so the continuation window starts clean.
        assert "one two three." not in drafts[1].text

    def test_whole_trailing_piece_within_budget_becomes_the_overlap(self) -> None:
        blocks = [
            text_block(words(5), "A"),
            text_block("one two.", "A"),
            text_block(words(6, "m"), "A"),
        ]
        drafts = chunk(blocks, max_tokens=10, overlap_tokens=5)
        assert len(drafts) == 2
        # The entire trailing sentence fits the overlap budget and is carried.
        assert drafts[1].text.split("\n", 1)[1].startswith("one two.")

    def test_no_overlap_across_heading_change(self) -> None:
        blocks = [
            text_block("Alpha content sentence one.", "A"),
            text_block("Bravo content sentence two.", "B"),
        ]
        drafts = chunk(blocks, max_tokens=30, overlap_tokens=10)
        assert len(drafts) == 2
        assert "Alpha" not in drafts[1].text


class TestOversizedBlocks:
    def test_oversized_prose_splits_on_sentence_boundaries(self) -> None:
        sentences = [f"{words(9, f's{i}')} end." for i in range(5)]  # 10 words each
        block = text_block(" ".join(sentences), "A")
        drafts = chunk([block], max_tokens=25)
        assert len(drafts) == 3
        joined = " ".join(d.text for d in drafts)
        for sentence in sentences:
            assert sentence in joined  # every sentence survives intact
        for draft in drafts:
            body = draft.text.split("\n", 1)[1]
            assert count_words(body) <= 25

    def test_giant_unpunctuated_run_splits_on_words(self) -> None:
        block = text_block(words(40))
        drafts = chunk([block], max_tokens=25)
        assert len(drafts) == 2
        assert count_words(drafts[0].text) == 25
        assert count_words(drafts[1].text) == 15
        assert " ".join(d.text for d in drafts) == words(40)

    def test_unbroken_run_beyond_word_splitting_bisects_on_characters(self) -> None:
        # A character-count tokenizer makes a single word overflow the budget,
        # forcing the last-resort character bisection.
        drafts = chunk_blocks(
            [text_block("abcdefghij")],
            max_tokens=4,
            overlap_tokens=0,
            count_tokens=len,
        )
        assert [d.text for d in drafts] == ["abcd", "efgh", "ij"]
        assert "".join(d.text for d in drafts) == "abcdefghij"

    def test_oversized_word_inside_prose_is_split_on_characters(self) -> None:
        drafts = chunk_blocks(
            [text_block("ab cdefgh")],
            max_tokens=4,
            overlap_tokens=0,
            count_tokens=len,
        )
        assert [d.text for d in drafts] == ["ab", "cdef", "gh"]


class TestPackingHelpers:
    """The greedy packers tolerate an empty unit list (no fragments out).

    Unreachable through ``chunk_blocks`` — blank blocks are stripped before
    packing — but part of the helpers' own contract.
    """

    def test_pack_units_of_nothing_yields_no_fragments(self) -> None:
        assert _pack_units([], " ", 10, count_words) == []

    def test_pack_units_flat_of_nothing_yields_no_fragments(self) -> None:
        assert _pack_units_flat([], 10, count_words) == []

    def test_split_by_chars_of_nothing_yields_no_fragments(self) -> None:
        assert _split_by_chars("", 4, len) == []


class TestTables:
    def test_table_that_fits_is_kept_whole_in_its_own_window(self) -> None:
        table_text = "\n".join(f"| r{i} | {words(4, f'c{i}')} |" for i in range(3))
        blocks = [
            text_block(words(20), "A"),
            ParsedBlock(kind=BlockKind.TABLE, text=table_text, heading_path=("A",)),
        ]
        drafts = chunk(blocks, max_tokens=25)
        assert len(drafts) == 2
        assert table_text in drafts[1].text

    def test_oversized_table_splits_on_row_boundaries(self) -> None:
        rows = [f"| r{i} | {words(4, f'c{i}')} |" for i in range(6)]  # 6 words per row
        block = ParsedBlock(kind=BlockKind.TABLE, text="\n".join(rows), heading_path=("A",))
        drafts = chunk([block], max_tokens=25)
        assert len(drafts) == 2
        for row in rows:
            assert sum(d.text.count(row) for d in drafts) == 1  # each row intact, once

    def test_table_text_is_never_used_as_overlap(self) -> None:
        table = ParsedBlock(kind=BlockKind.TABLE, text="| a | b |\n| 1 | 2 |", heading_path=("A",))
        after = text_block(words(10), "A")
        drafts = chunk([table, after], max_tokens=12, overlap_tokens=6)
        assert len(drafts) == 2
        assert "| a | b |" not in drafts[1].text


class TestDeterminism:
    def test_same_input_same_output(self) -> None:
        blocks = [
            text_block("Intro paragraph with some sentences. And a second one."),
            text_block(words(30), "A", "A.1"),
            ParsedBlock(kind=BlockKind.TABLE, text="| x | y |", heading_path=("A", "A.2")),
            text_block(words(60, "z"), "B"),
        ]
        first = chunk(blocks, max_tokens=24, overlap_tokens=6)
        second = chunk(blocks, max_tokens=24, overlap_tokens=6)
        assert first == second
        assert first  # non-trivial input actually produced chunks

    def test_sequential_text_order_is_preserved(self) -> None:
        blocks = [text_block(words(20, f"p{i}"), "A") for i in range(4)]
        drafts = chunk(blocks, max_tokens=30)
        flat = " ".join(d.text for d in drafts)
        positions = [flat.index(f"p{i}0") for i in range(4)]
        assert positions == sorted(positions)
