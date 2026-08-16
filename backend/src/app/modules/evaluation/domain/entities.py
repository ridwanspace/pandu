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
    """One human-curated question/answer/source triple from the golden set."""

    id: str
    question: str
    reference_answer: str
    # Filenames (and optional heading hints) of chunks that must be retrieved.
    source_files: tuple[str, ...]
    source_hints: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RetrievalScores:
    recall_at_k: float
    mrr: float
    k: int
    examples: int


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
