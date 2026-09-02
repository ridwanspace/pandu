"""Abstention scoring — does the system know when *not* to answer?

Almost every RAG evaluation optimises "answer well" and never measures "know
when to stay quiet". That gap is not academic: in a regulated setting a
confident wrong answer is worse than no answer at all, because no answer
routes to a human while a wrong answer routes to a regulator.

Measuring it needs two things this module supplies:

1. **Negatives in the golden set** — questions the corpus genuinely cannot
   answer (:attr:`GoldenExample.answerable` is ``False``). A dataset of only
   answerable questions can never catch a system that answers everything.
2. **A detector** — :func:`is_abstention`, which decides whether a generated
   answer actually declined. It is deliberately a *lexical* check over a
   closed phrase list rather than an LLM call: the abstention metric must stay
   deterministic and free so it can gate every push, alongside recall@k and
   MRR (see :mod:`.metrics`).

The two error directions are reported separately because they cost different
things — see :class:`~.entities.AbstentionScores`.
"""

from __future__ import annotations

from collections.abc import Iterable

from app.modules.evaluation.domain.entities import AbstentionScores
from app.shared.domain.errors import InvalidInputError

# Phrases a grounded assistant uses when the context does not carry the answer.
# Kept explicit (not a regex soup) so adding a phrase is an obvious, reviewable
# change. Matching is case-insensitive substring matching over the whole answer.
#
# Maintenance rule: this list is validated against the golden set by
# ``test_golden_negatives_are_detected`` — every negative's reference answer
# must read as a refusal, and no answerable example's reference answer may.
# That test is how a missing phrase gets caught instead of quietly costing
# abstention recall.
ABSTENTION_MARKERS: tuple[str, ...] = (
    "does not contain",
    "does not specify",
    "does not say",
    "does not provide",
    "does not mention",
    "does not cover",
    "does not address",
    "does not include",
    "does not describe",
    "is not covered",
    "is not addressed",
    "is out of scope",
    "outside the scope",
    "not contain the answer",
    "no information",
    "not in the provided context",
    "not in the context",
    "context does not",
    "cannot answer",
    "can't answer",
    "unable to answer",
    "insufficient context",
    "context is insufficient",
    "not covered",
    "not addressed",
)


def is_abstention(answer: str) -> bool:
    """True when *answer* declines to answer from the retrieved context.

    An empty or whitespace-only answer counts as an abstention: the system
    produced no claim, so it asserted nothing that could be wrong.

    The check is intentionally conservative about what it treats as a refusal.
    A false negative here (a real refusal we fail to detect) shows up as a
    *worse* abstention score, which is the safe direction for a gate — the
    metric under-reports our ability to decline rather than over-reporting it.
    """
    normalized = answer.strip().casefold()
    if not normalized:
        return True
    return any(marker in normalized for marker in ABSTENTION_MARKERS)


def score_abstention(results: Iterable[tuple[bool, bool]]) -> AbstentionScores:
    """Score ``(answerable, abstained)`` pairs into :class:`AbstentionScores`.

    ``abstention_recall`` is the fraction of negatives correctly declined;
    ``false_abstention_rate`` the fraction of answerable examples wrongly
    declined. Each is reported as ``0.0`` when its population is empty — with
    the population size alongside it, so "0.0 because perfect" can never be
    confused with "0.0 because there was nothing to measure".

    Raises :class:`InvalidInputError` for zero examples: an empty run
    reporting any score would be a lie.
    """
    negatives = 0
    correct_abstentions = 0
    positives = 0
    false_abstentions = 0

    for answerable, abstained in results:
        if answerable:
            positives += 1
            if abstained:
                false_abstentions += 1
        else:
            negatives += 1
            if abstained:
                correct_abstentions += 1

    if positives + negatives == 0:
        raise InvalidInputError("cannot score abstention over zero examples")

    return AbstentionScores(
        abstention_recall=(correct_abstentions / negatives) if negatives else 0.0,
        false_abstention_rate=(false_abstentions / positives) if positives else 0.0,
        negatives=negatives,
        positives=positives,
    )
