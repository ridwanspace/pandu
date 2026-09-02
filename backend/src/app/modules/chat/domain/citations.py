"""Citation-marker analysis of generated answers. Pure functions.

Grounding is asserted here, not asked for in the prompt: a model can emit any
``[n]`` it likes, so the only trustworthy check is to compare the markers in the
answer against the markers we actually handed it. Filtering silently (the old
behaviour) hid hallucinated markers; :func:`validate_citations` reports them.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from app.modules.chat.domain.entities import Citation

_MARKER_RE = re.compile(r"\[(\d+)\]")


def extract_marker_set(text: str) -> set[int]:
    """All inline citation markers ``[n]`` present in *text*."""
    return {int(match) for match in _MARKER_RE.findall(text)}


@dataclass(frozen=True, slots=True)
class CitationReport:
    """Outcome of checking one answer's markers against the retrieved set.

    Frozen so a report can be annotated onto a trace or passed around without
    any chance of a caller mutating the verdict after the fact.
    """

    cited: tuple[Citation, ...]
    """Retrieved citations the answer actually referenced, in retrieval order."""

    invalid_markers: tuple[int, ...]
    """Markers in the answer with no retrieved source — sorted, deduped.

    These are the hallucinations: ``[9]`` when only three sources were given,
    or ``[0]`` when markers start at 1.
    """

    uncited_markers: tuple[int, ...]
    """Retrieved markers the answer never referenced — sorted.

    Not an error; a useful signal that retrieval returned more than the answer
    needed (or that the model ignored context).
    """

    @property
    def is_valid(self) -> bool:
        """True when every marker the answer emitted maps to a real source."""
        return not self.invalid_markers

    @property
    def validity(self) -> float:
        """Fraction of the answer's DISTINCT markers that resolved to a source.

        An answer that cites nothing scores 1.0 rather than 0.0: abstention
        ("the context does not cover this") is the desired behaviour under our
        grounded prompt, and scoring it as a total hallucination would punish
        exactly the response we want. Repeated markers count once, so a single
        bad marker repeated ten times does not dominate the score.
        """
        total = len(self.cited) + len(self.invalid_markers)
        if total == 0:
            return 1.0
        return len(self.cited) / total


def validate_citations(citations: Sequence[Citation], text: str) -> CitationReport:
    """Check the markers in *text* against the retrieved *citations*, in one pass.

    Retrieval hands the model k sources numbered 1..k; this asserts the answer
    only referenced those, so a hallucinated marker becomes a measurable count
    instead of a silently dropped entry.
    """
    markers = extract_marker_set(text)
    cited = tuple(citation for citation in citations if citation.marker in markers)
    retrieved_markers = {citation.marker for citation in citations}
    return CitationReport(
        cited=cited,
        invalid_markers=tuple(sorted(markers - retrieved_markers)),
        uncited_markers=tuple(sorted(retrieved_markers - markers)),
    )


def used_citations(citations: Sequence[Citation], text: str) -> tuple[Citation, ...]:
    """Filter *citations* to those actually cited in *text*, preserving order.

    Retrieval hands the model k sources; the persisted message keeps only the
    ones the answer referenced, so the UI can distinguish retrieved vs cited.
    Kept as the narrow accessor over :func:`validate_citations` for callers that
    only need the surviving citations.
    """
    return validate_citations(citations, text).cited
