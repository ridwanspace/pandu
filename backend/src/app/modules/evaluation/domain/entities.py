"""Evaluation module — domain entities.

Retrieval metrics (recall@k, MRR) are deterministic and LLM-free; generation
metrics (ragas, LLM-as-judge) cost tokens. The split is deliberate — see §7 of
the architecture review.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class GoldenExample:
    """One human-curated question/answer/source triple from the golden set.

    ``answerable=False`` marks a *negative*: a question the corpus genuinely
    cannot answer. Negatives are what make abstention measurable at all — a
    set of only answerable questions can never catch a system that answers
    everything confidently. For a negative, ``source_files`` is empty and the
    ``reference_answer`` records what a correct refusal should convey.
    """

    id: str
    question: str
    reference_answer: str
    # Filenames (and optional heading hints) of chunks that must be retrieved.
    # Empty for negatives: there is no correct source to retrieve.
    source_files: tuple[str, ...]
    source_hints: tuple[str, ...] = ()
    answerable: bool = True


@dataclass(frozen=True, slots=True)
class RetrievalScores:
    """One eval run's rank-quality summary, all measured at the same ``k``.

    Five metrics because each hides a different failure: recall misses how high
    the evidence ranked, MRR ignores everything after the first hit, precision
    exposes padding, hit rate separates "nothing" from "partial" on
    cross-document questions, and nDCG rewards ordering the other four flatten.
    """

    recall_at_k: float
    mrr: float
    k: int
    examples: int
    precision_at_k: float
    hit_rate_at_k: float
    ndcg_at_k: float


@dataclass(frozen=True, slots=True)
class AbstentionScores:
    """How well the system knows when *not* to answer.

    Two error directions, deliberately kept apart because they cost different
    things: a false answer on an unanswerable question is a confident wrong
    answer (in a regulated setting, the expensive one), while a false
    abstention on an answerable question is a needless escalation.
    """

    # Of the negatives, the fraction the system correctly declined to answer.
    abstention_recall: float
    # Of the answerable examples, the fraction wrongly declined.
    false_abstention_rate: float
    negatives: int
    positives: int


@dataclass(frozen=True, slots=True)
class JudgeVerdict:
    example_id: str
    faithfulness: float  # 0..1: is the answer grounded in retrieved context?
    relevancy: float  # 0..1: does it answer the question?
    reasoning: str


@dataclass(slots=True)
class EvalRun:
    id: UUID
    created_at: datetime
    dataset_version: str
    config: dict[str, str] = field(default_factory=dict)
    metrics: dict[str, float] = field(default_factory=dict)
