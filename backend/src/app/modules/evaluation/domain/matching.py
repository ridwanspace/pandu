"""Golden-set relevance matching.

The golden set labels relevance at the *source-file* level (plus optional
textual hints), never at the chunk level: chunk ids change whenever the
chunking config changes, so chunk-level labels would rot on every re-ingest.
File-level labels survive re-chunking; hints narrow matches inside large
documents (SP 800-53r5 is ~500 pages — "the right file" alone is weak
evidence there).
"""

from __future__ import annotations


def hint_matches(hint: str, *, text: str, heading_path: tuple[str, ...]) -> bool:
    """True when ``hint`` occurs case-insensitively in the chunk text or in
    any segment of its heading path.

    Substring (not token) matching is deliberate: hints like "AAL2" or
    "multi-factor" must match regardless of surrounding punctuation.
    """
    needle = hint.casefold()
    if needle in text.casefold():
        return True
    return any(needle in segment.casefold() for segment in heading_path)


def matched_source(
    *,
    filename: str,
    text: str,
    heading_path: tuple[str, ...],
    source_files: tuple[str, ...],
    source_hints: tuple[str, ...] = (),
) -> str | None:
    """Return the golden source filename this chunk counts as evidence for,
    or ``None`` when the chunk is not relevant to the example.

    A chunk is relevant iff its filename is one of the example's source files
    AND — when the example carries hints — at least one hint matches the chunk
    content. Without hints, any chunk from a source file counts.
    """
    if filename not in source_files:
        return None
    if source_hints and not any(
        hint_matches(hint, text=text, heading_path=heading_path) for hint in source_hints
    ):
        return None
    return filename
