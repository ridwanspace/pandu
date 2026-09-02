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

from app.modules.evaluation.domain.abstention import is_abstention, score_abstention
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

# Mirrors the production chat instruction (chat.domain.prompting) on the one
# axis this eval measures: answer only from context, and say so when it is not
# there. Kept local because the evaluation module must not import the chat
# module (import-linter enforces module independence).
ABSTENTION_SYSTEM_PROMPT = (
    "Answer the question using ONLY the numbered context passages provided. "
    "If the passages do not contain the answer, reply that the context does not "
    "contain the information needed and do not attempt to answer from prior "
    "knowledge. Never invent facts or sources."
)


class RunRetrievalEval:
    """Score the retrieval pipeline against the golden set.

    Reports recall@k, MRR, precision@k, hit rate@k and nDCG@k — all LLM-free
    and all at one shared ``k``, so a run is a single coherent snapshot.
    """

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
        # Negatives carry no source files, so rank metrics are undefined for
        # them — they are scored by RunAbstentionEval instead. Mixing them in
        # here would silently drag recall toward zero and make the gate
        # meaningless.
        scored = [example for example in examples if example.answerable]
        if not scored:
            raise InvalidInputError("golden dataset contains no answerable examples")
        results: list[tuple[frozenset[str], tuple[str, ...]]] = []
        for example in scored:
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
                "precision_at_k": scores.precision_at_k,
                "hit_rate_at_k": scores.hit_rate_at_k,
                "ndcg_at_k": scores.ndcg_at_k,
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
        # Negatives are excluded, for the same reason they are excluded from
        # rank metrics: the rubric asks whether the reference answer's claims
        # are supported by the retrieved passages, and a negative's reference
        # answer is a *refusal* whose supporting evidence is the corpus's
        # silence. Asking "do these passages support 'the corpus does not
        # cover HIPAA'?" is not a well-posed question, and measurement bears
        # that out: scored on the 5 negatives the judge returned
        # 0.0/1.0/0.0/1.0/1.0 — noise, not signal, mixed straight into the
        # mean. Abstention on negatives is measured by RunAbstentionEval,
        # which asks a question that has an answer.
        scored = [example for example in examples if example.answerable]
        if not scored:
            raise InvalidInputError("golden dataset contains no answerable examples to judge")
        verdicts: list[JudgeVerdict] = []
        for example in scored:
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
            # The judge model is part of the eval's DEFINITION, not an
            # implementation detail: the same suite can pass under one judge
            # and fail under another. Record what actually answered, which
            # may differ from what was requested if a fallback fired.
            verdict, resolved_judge = await self._judge_once(example, request)
            verdicts.append(verdict)
        count = len(verdicts)
        run = EvalRun(
            id=uuid4(),
            created_at=datetime.now(UTC),
            dataset_version=f"{self._dataset_version}-judge",
            config={**self._config, "judge_model_resolved": resolved_judge},
            metrics={
                "faithfulness": sum(v.faithfulness for v in verdicts) / count,
                "relevancy": sum(v.relevancy for v in verdicts) / count,
                "examples": float(count),
            },
        )
        await self._runs.add(run)
        return run

    async def _judge_once(
        self, example: GoldenExample, request: CompletionRequest
    ) -> tuple[JudgeVerdict, str]:
        """One judged example, retried once on an empty completion.

        Reasoning models emit hidden thinking before the verdict, and the
        length of that thinking is highly variable: measured on one example,
        the same prompt at temperature 0 consumed between 548 and 4295
        completion tokens across six runs. A fixed budget is therefore not a
        guarantee — an unlucky tail spends the whole cap reasoning and returns
        nothing.

        Retrying once is the honest fix. Note what this is NOT: it is not
        averaging repeated judgements to smooth out variance, which would
        silently turn truncations into scores. A non-empty verdict is parsed
        strictly, exactly as before; only the empty case is retried, and a
        second empty response still fails the run loudly.
        """
        result = await self._judge.complete(request)
        if not result.text.strip():
            result = await self._judge.complete(request)
        return parse_verdict(example.id, result.text), str(result.model)


class RunAbstentionEval:
    """Measure whether the system declines when the corpus cannot answer.

    Costs one generation per example (not a judge call): abstention is a
    property of the *answer*, so it has to be generated before it can be
    scored. The scoring itself is deterministic and LLM-free — see
    :mod:`app.modules.evaluation.domain.abstention`.

    Requires negatives in the dataset; without them the metric is vacuous, so
    a dataset of only answerable examples fails loudly rather than reporting a
    meaningless 0.0.
    """

    def __init__(
        self,
        *,
        answerer: LLMProvider,
        retrieve: RetrieveContext,
        runs: EvalRunRepository,
        dataset_loader: DatasetLoader,
        dataset_version: str,
        config: dict[str, str],
        max_output_tokens: int = 512,
    ) -> None:
        self._answerer = answerer
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
        if not any(not example.answerable for example in examples):
            raise InvalidInputError(
                "abstention eval requires at least one unanswerable example; "
                "a dataset of only answerable questions cannot measure abstention"
            )

        results: list[tuple[bool, bool]] = []
        for example in examples:
            context = await self._retrieve(RetrievalQuery(text=example.question))
            answer = await self._answer(example.question, context)
            results.append((example.answerable, is_abstention(answer)))

        scores = score_abstention(results)
        run = EvalRun(
            id=uuid4(),
            created_at=datetime.now(UTC),
            dataset_version=f"{self._dataset_version}-abstention",
            config=dict(self._config),
            metrics={
                "abstention_recall": scores.abstention_recall,
                "false_abstention_rate": scores.false_abstention_rate,
                "negatives": float(scores.negatives),
                "positives": float(scores.positives),
            },
        )
        await self._runs.add(run)
        return run

    async def _answer(self, question: str, context: RetrievedContext) -> str:
        """Generate one grounded answer for *question* over the retrieved contexts."""
        numbered = "\n\n".join(
            f"[{index}] {chunk.text}" for index, chunk in enumerate(context.chunks, start=1)
        )
        if not numbered:
            numbered = "(no passages were retrieved)"
        request = CompletionRequest(
            messages=(
                ChatMessage(role="system", content=ABSTENTION_SYSTEM_PROMPT),
                ChatMessage(role="user", content=f"Context:\n\n{numbered}\n\nQuestion: {question}"),
            ),
            temperature=0.0,
            max_output_tokens=self._max_output_tokens,
            tags=("eval", "abstention"),
        )
        result = await self._answerer.complete(request)
        return result.text


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
