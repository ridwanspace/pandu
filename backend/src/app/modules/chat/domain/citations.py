"""Citation-marker analysis of generated answers. Pure functions."""

from __future__ import annotations

import re
from collections.abc import Sequence

from app.modules.chat.domain.entities import Citation

_MARKER_RE = re.compile(r"\[(\d+)\]")


def extract_marker_set(text: str) -> set[int]:
    """All inline citation markers ``[n]`` present in *text*."""
    return {int(match) for match in _MARKER_RE.findall(text)}


def used_citations(citations: Sequence[Citation], text: str) -> tuple[Citation, ...]:
    """Filter *citations* to those actually cited in *text*, preserving order.

    Retrieval hands the model k sources; the persisted message keeps only the
    ones the answer referenced, so the UI can distinguish retrieved vs cited.
    """
    markers = extract_marker_set(text)
    return tuple(citation for citation in citations if citation.marker in markers)
