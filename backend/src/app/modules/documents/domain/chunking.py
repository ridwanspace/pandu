"""Structure-aware chunking of parsed document blocks.

Pure domain logic: token counting arrives as an injected callable so this
module stays stdlib-only (tiktoken lives in infrastructure).

Invariants:
- A block whose body fits within ``max_tokens`` is never split.
- Consecutive blocks whose heading paths share a common prefix are packed
  into windows of at most ``max_tokens`` body tokens.
- When a window overflows inside the same heading group, the next window is
  seeded with the trailing sentences (~``overlap_tokens``) of the previous
  one, so context survives the cut. Heading changes never overlap.
- Oversized prose blocks split on sentence boundaries; tables and code split
  on line boundaries so rows/lines stay intact.
- The heading trail is prepended to the chunk text ("§ A > B") so an embedded
  chunk carries its own context. The budget governs the body; the reported
  ``token_count`` is measured on the full rendered text.

The output is deterministic for a given input and token counter.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from app.modules.documents.domain.parser import BlockKind, ParsedBlock

TokenCounter = Callable[[str], int]

_HEADING_MARKER = "§ "
_HEADING_JOINER = " > "
_BLOCK_SEPARATOR = "\n\n"

# A sentence ends at ., ! or ? followed by whitespace. Deliberately simple:
# abbreviations may over-split, which only costs slightly smaller pieces.
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+")

_LINE_KINDS = frozenset({BlockKind.TABLE, BlockKind.CODE})


@dataclass(frozen=True, slots=True)
class ChunkDraft:
    """A chunk before identity/embedding are attached (see ``entities.Chunk``)."""

    text: str
    token_count: int
    heading_path: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _Piece:
    """A block, or a fragment of an oversized block, ready for packing."""

    text: str
    heading_path: tuple[str, ...]
    kind: BlockKind


def chunk_blocks(
    blocks: Sequence[ParsedBlock],
    *,
    max_tokens: int,
    overlap_tokens: int,
    count_tokens: TokenCounter,
) -> list[ChunkDraft]:
    """Pack parsed blocks into retrieval chunks. See module docstring for rules."""
    if max_tokens <= 0:
        msg = f"max_tokens must be positive, got {max_tokens}"
        raise ValueError(msg)
    if overlap_tokens < 0 or overlap_tokens >= max_tokens:
        msg = f"overlap_tokens must be in [0, max_tokens), got {overlap_tokens}"
        raise ValueError(msg)

    pieces = _prepare_pieces(blocks, max_tokens, count_tokens)

    drafts: list[ChunkDraft] = []
    window: list[_Piece] = []
    window_prefix: tuple[str, ...] = ()
    overlap_text = ""

    def flush() -> None:
        body = _join_body(overlap_text, window)
        text = _render(window_prefix, body)
        drafts.append(
            ChunkDraft(text=text, token_count=count_tokens(text), heading_path=window_prefix)
        )

    for piece in pieces:
        if not window:
            window = [piece]
            window_prefix = piece.heading_path
            continue
        if _same_group(window_prefix, piece.heading_path):
            merged = _common_prefix(window_prefix, piece.heading_path)
            candidate = _join_body(overlap_text, [*window, piece])
            if count_tokens(candidate) <= max_tokens:
                window.append(piece)
                window_prefix = merged
                continue
            # Overflow inside one heading group: cut here, carry overlap over.
            carry = _overlap_tail(window[-1], overlap_tokens, count_tokens)
            flush()
            overlap_text = carry
            if overlap_text and count_tokens(_join_body(overlap_text, [piece])) > max_tokens:
                overlap_text = ""
        else:
            # Topic change: hard boundary, no overlap across headings.
            flush()
            overlap_text = ""
        window = [piece]
        window_prefix = piece.heading_path

    if window:
        flush()
    return drafts


def _prepare_pieces(
    blocks: Sequence[ParsedBlock],
    max_tokens: int,
    count_tokens: TokenCounter,
) -> list[_Piece]:
    """Drop headings/empties and split oversized blocks into packable pieces."""
    pieces: list[_Piece] = []
    for block in blocks:
        if block.kind is BlockKind.HEADING:
            continue  # Headings travel as heading_path context, not as content.
        text = block.text.strip()
        if not text:
            continue
        for fragment in _fit_block(text, block.kind, max_tokens, count_tokens):
            pieces.append(_Piece(text=fragment, heading_path=block.heading_path, kind=block.kind))
    return pieces


def _fit_block(
    text: str,
    kind: BlockKind,
    max_tokens: int,
    count_tokens: TokenCounter,
) -> list[str]:
    """Return the block whole if it fits, otherwise split it on natural seams."""
    if count_tokens(text) <= max_tokens:
        return [text]
    if kind in _LINE_KINDS:
        units = [line for line in text.splitlines() if line.strip()]
        separator = "\n"
    else:
        units = _split_sentences(text)
        separator = " "
    return _pack_units(units, separator, max_tokens, count_tokens)


def _pack_units(
    units: Sequence[str],
    separator: str,
    max_tokens: int,
    count_tokens: TokenCounter,
) -> list[str]:
    """Greedily join units into fragments of at most ``max_tokens`` each."""
    fragments: list[str] = []
    current: list[str] = []
    for unit in units:
        parts = (
            [unit]
            if count_tokens(unit) <= max_tokens
            else _split_by_tokens(unit, max_tokens, count_tokens)
        )
        for part in parts:
            candidate = separator.join([*current, part])
            if current and count_tokens(candidate) > max_tokens:
                fragments.append(separator.join(current))
                current = [part]
            else:
                current = [*current, part]
    if current:
        fragments.append(separator.join(current))
    return fragments


def _split_by_tokens(text: str, max_tokens: int, count_tokens: TokenCounter) -> list[str]:
    """Last resort for a single unit above the budget: whitespace, then chars."""
    words = text.split()
    if len(words) > 1:
        return _pack_units_flat(words, max_tokens, count_tokens)
    return _split_by_chars(text, max_tokens, count_tokens)


def _pack_units_flat(
    words: Sequence[str], max_tokens: int, count_tokens: TokenCounter
) -> list[str]:
    fragments: list[str] = []
    current: list[str] = []
    for word in words:
        parts = (
            [word]
            if count_tokens(word) <= max_tokens
            else _split_by_chars(word, max_tokens, count_tokens)
        )
        for part in parts:
            candidate = " ".join([*current, part])
            if current and count_tokens(candidate) > max_tokens:
                fragments.append(" ".join(current))
                current = [part]
            else:
                current = [*current, part]
    if current:
        fragments.append(" ".join(current))
    return fragments


def _split_by_chars(text: str, max_tokens: int, count_tokens: TokenCounter) -> list[str]:
    """Bisect a pathological unbroken run so every fragment fits the budget."""
    fragments: list[str] = []
    rest = text
    while rest:
        if count_tokens(rest) <= max_tokens:
            fragments.append(rest)
            break
        lo, hi = 1, len(rest)  # Largest prefix length whose token count fits.
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if count_tokens(rest[:mid]) <= max_tokens:
                lo = mid
            else:
                hi = mid - 1
        fragments.append(rest[:lo])
        rest = rest[lo:]
    return fragments


def _split_sentences(text: str) -> list[str]:
    return [part for part in _SENTENCE_BOUNDARY.split(text) if part.strip()]


def _overlap_tail(piece: _Piece, overlap_tokens: int, count_tokens: TokenCounter) -> str:
    """Trailing sentences of ``piece`` totalling at most ``overlap_tokens``.

    Tables and code are never duplicated into the next window: a partial table
    or code fragment out of context is noise, not signal.
    """
    if overlap_tokens <= 0 or piece.kind in _LINE_KINDS:
        return ""
    tail: list[str] = []
    total = 0
    for sentence in reversed(_split_sentences(piece.text)):
        tokens = count_tokens(sentence)
        if total + tokens > overlap_tokens:
            break
        tail.insert(0, sentence)
        total += tokens
    return " ".join(tail)


def _same_group(a: tuple[str, ...], b: tuple[str, ...]) -> bool:
    """Blocks pack together when their heading paths share a prefix.

    Two unheaded blocks (both paths empty) also belong together.
    """
    if not a and not b:
        return True
    return bool(_common_prefix(a, b))


def _common_prefix(a: tuple[str, ...], b: tuple[str, ...]) -> tuple[str, ...]:
    prefix: list[str] = []
    for left, right in zip(a, b, strict=False):
        if left != right:
            break
        prefix.append(left)
    return tuple(prefix)


def _join_body(overlap_text: str, pieces: Sequence[_Piece]) -> str:
    parts = ([overlap_text] if overlap_text else []) + [p.text for p in pieces]
    return _BLOCK_SEPARATOR.join(parts)


def _render(heading_path: tuple[str, ...], body: str) -> str:
    if not heading_path:
        return body
    return _HEADING_MARKER + _HEADING_JOINER.join(heading_path) + "\n" + body
