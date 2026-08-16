"""Evaluation use cases.

``RunRetrievalEval`` is LLM-free and deterministic — it replays the golden
questions through the live retrieval pipeline and scores rank quality.
``RunJudgeEval`` costs tokens: it asks a judge model to grade the retrieved
contexts against each reference answer. Keeping them as separate use cases
keeps "cheap, every push" and "expensive, on demand" independently wireable.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from app.modules.evaluation.domain.entities import EvalRun, GoldenExample, JudgeVerdict
from app.modules.evaluation.domain.judging import (
    JUDGE_SYSTEM_PROMPT,
    build_judge_prompt,
    parse_verdict,
)
from app.modules.evaluation.domain.matching import matched_source
from app.modules.evaluation.domain.metrics import aggregate
from app.modules.evaluation.domain.repositories import EvalRunRepository
from app.modules.retrieval.application.dto import RetrievalQuery, RetrievedContext
from app.shared.domain.errors import InvalidInputError
from app.shared.domain.ports.llm import ChatMessage, CompletionRequest, LLMProvider

if TYPE_CHECKING:  # runtime-safe: the eval module must import while retrieval is wired later
    from app.modules.retrieval.application.use_cases import RetrieveContext

DatasetLoader = Callable[[], tuple[GoldenExample, ...]]


class RunRetrievalEval:
    """Score the retrieval pipeline against the golden set (recall@k, MRR)."""

    def __init__(
        self,
        *,
        retrieve: RetrieveContext,
        runs: EvalRunRepository,
        dataset_loader: DatasetLoader,
        k: int,
        dataset_version: str,
        config: dict[str, str],
    ) -> None:
        self._retrieve = retrieve
        self._runs = runs
        self._dataset_loader = dataset_loader
        self._k = k
        self._dataset_version = dataset_version
        self._config = config

    async def __call__(self, *, k: int | None = None) -> EvalRun:
        """Run the eval; ``k`` overrides the wired default for this run only."""
        effective_k = self._k if k is None else k
        if effective_k <= 0:
            raise InvalidInputError(f"k must be positive, got {effective_k}")
        examples = self._dataset_loader()
        results: list[tuple[frozenset[str], tuple[str, ...]]] = []
        for example in examples:
            context = await self._retrieve(RetrievalQuery(text=example.question))
            results.append((frozenset(example.source_files), _retrieved_ids(example, context)))
        scores = aggregate(results, k=effective_k)
        run = EvalRun(
            id=uuid4(),
            created_at=datetime.now(UTC),
            dataset_version=self._dataset_version,
            config={**self._config, "k": str(effective_k)},
            metrics={
                "recall_at_k": scores.recall_at_k,
                "mrr": scores.mrr,
                "examples": float(scores.examples),
            },
        )
        await self._runs.add(run)
        return run


class RunJudgeEval:
    """LLM-as-judge over the golden set: grade retrieved contexts per example.

    One completion per example, temperature 0, strict JSON output. Aggregates
    mean faithfulness/relevancy; a single malformed verdict fails the run —
    see :mod:`app.modules.evaluation.domain.judging` for why.
    """

    def __init__(
        self,
        *,
        judge: LLMProvider,
        retrieve: RetrieveContext,
        runs: EvalRunRepository,
        dataset_loader: DatasetLoader,
        dataset_version: str,
        config: dict[str, str],
        max_output_tokens: int = 512,
    ) -> None:
        self._judge = judge
        self._retrieve = retrieve
        self._runs = runs
        self._dataset_loader = dataset_loader
        self._dataset_version = dataset_version
        self._config = config
        self._max_output_tokens = max_output_tokens

    async def __call__(self) -> EvalRun:
        examples = self._dataset_loader()
        if not examples:
            raise InvalidInputError("golden dataset is empty")
        verdicts: list[JudgeVerdict] = []
        for example in examples:
            context = await self._retrieve(RetrievalQuery(text=example.question))
            prompt = build_judge_prompt(
                question=example.question,
                reference_answer=example.reference_answer,
                contexts=tuple(chunk.text for chunk in context.chunks),
            )
            request = CompletionRequest(
                messages=(
                    ChatMessage(role="system", content=JUDGE_SYSTEM_PROMPT),
                    ChatMessage(role="user", content=prompt),
                ),
                temperature=0.0,
                max_output_tokens=self._max_output_tokens,
                tags=("eval", "judge"),
            )
            result = await self._judge.complete(request)
            verdicts.append(parse_verdict(example.id, result.text))
        count = len(verdicts)
        run = EvalRun(
            id=uuid4(),
            created_at=datetime.now(UTC),
            dataset_version=f"{self._dataset_version}-judge",
            config=dict(self._config),
            metrics={
                "faithfulness": sum(v.faithfulness for v in verdicts) / count,
                "relevancy": sum(v.relevancy for v in verdicts) / count,
                "examples": float(count),
            },
        )
        await self._runs.add(run)
        return run


class ListEvalRuns:
    """Most recent eval runs, for the dashboard and the API."""

    def __init__(self, *, runs: EvalRunRepository) -> None:
        self._runs = runs

    async def __call__(self, *, limit: int = 20) -> list[EvalRun]:
        if limit <= 0:
            raise InvalidInputError(f"limit must be positive, got {limit}")
        return await self._runs.list_recent(limit)


def _retrieved_ids(example: GoldenExample, context: RetrievedContext) -> tuple[str, ...]:
    """Map ranked chunks to metric ids: the matched source filename, or a
    per-position miss marker so irrelevant chunks still consume rank slots."""
    ids: list[str] = []
    for position, chunk in enumerate(context.chunks):
        matched = matched_source(
            filename=chunk.filename,
            text=chunk.text,
            heading_path=chunk.heading_path,
            source_files=example.source_files,
            source_hints=example.source_hints,
        )
        ids.append(matched if matched is not None else f"__miss_{position}")
    return tuple(ids)
