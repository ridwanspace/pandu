"""Evaluation use cases with hand-written fakes — no DB, network, or LLM."""

from __future__ import annotations

import json
from uuid import uuid4

import pytest

from app.modules.evaluation.application.use_cases import (
    ListEvalRuns,
    RunAbstentionEval,
    RunJudgeEval,
    RunRetrievalEval,
)
from app.modules.evaluation.domain.entities import EvalRun, GoldenExample
from app.modules.retrieval.application.dto import RetrievalQuery, RetrievedContext
from app.modules.retrieval.domain.entities import RankedChunk
from app.shared.domain.errors import InvalidInputError
from app.shared.domain.ports.llm import (
    CompletionRequest,
    CompletionResult,
    StreamEvent,
)
from app.shared.domain.values import ModelRef, TokenUsage

# ── Fixtures ─────────────────────────────────────────────────────────────────


def _chunk(filename: str, text: str = "body", heading: tuple[str, ...] = ()) -> RankedChunk:
    return RankedChunk(
        chunk_id=uuid4(),
        document_id=uuid4(),
        seq=0,
        text=text,
        filename=filename,
        heading_path=heading,
        fused_score=1.0,
    )


def _context(*chunks: RankedChunk) -> RetrievedContext:
    return RetrievedContext(
        chunks=chunks,
        candidate_count=len(chunks),
        reranker="none",
        embed_latency_ms=1,
        search_latency_ms=1,
        rerank_latency_ms=0,
    )


class FakeRetrieve:
    """Canned RetrievedContext per question text."""

    def __init__(self, by_question: dict[str, RetrievedContext]) -> None:
        self._by_question = by_question
        self.queries: list[RetrievalQuery] = []

    async def __call__(
        self, query: RetrievalQuery, *, trace_id: str | None = None
    ) -> RetrievedContext:
        self.queries.append(query)
        return self._by_question[query.text]


class InMemoryEvalRunRepository:
    def __init__(self) -> None:
        self.runs: list[EvalRun] = []

    async def add(self, run: EvalRun) -> None:
        self.runs.append(run)

    async def list_recent(self, limit: int) -> list[EvalRun]:
        ordered = sorted(self.runs, key=lambda r: r.created_at, reverse=True)
        return ordered[:limit]


class FakeJudge:
    """LLMProvider fake replaying queued completion texts in call order."""

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.requests: list[CompletionRequest] = []

    async def complete(self, request: CompletionRequest) -> CompletionResult:
        self.requests.append(request)
        return CompletionResult(
            text=self._responses.pop(0),
            usage=TokenUsage(prompt_tokens=10, completion_tokens=5),
            model=ModelRef(provider="fake", name="judge"),
        )

    def stream(self, request: CompletionRequest) -> _NoStream:
        raise NotImplementedError


class _NoStream:
    def __aiter__(self) -> _NoStream:
        return self

    async def __anext__(self) -> StreamEvent:
        raise StopAsyncIteration


EXAMPLES = (
    GoldenExample(
        id="ex1",
        question="q1",
        reference_answer="ref1",
        source_files=("a.pdf",),
        source_hints=("alpha",),
    ),
    GoldenExample(
        id="ex2",
        question="q2",
        reference_answer="ref2",
        source_files=("a.pdf", "b.pdf"),
    ),
)

CONTEXTS = {
    # ex1: rank 1 irrelevant, rank 2 hits a.pdf AND the "alpha" hint.
    "q1": _context(_chunk("b.pdf"), _chunk("a.pdf", text="mentions ALPHA topic")),
    # ex2 (cross-document): a.pdf found twice, b.pdf never → recall 0.5.
    "q2": _context(_chunk("a.pdf"), _chunk("x.pdf"), _chunk("a.pdf")),
}


def _loader() -> tuple[GoldenExample, ...]:
    return EXAMPLES


def _retrieval_eval(
    retrieve: FakeRetrieve, runs: InMemoryEvalRunRepository, k: int = 3
) -> RunRetrievalEval:
    return RunRetrievalEval(
        retrieve=retrieve,  # type: ignore[arg-type]  # structural fake
        runs=runs,
        dataset_loader=_loader,
        k=k,
        dataset_version="golden_test",
        config={"reranker": "none"},
    )


# ── RunRetrievalEval ─────────────────────────────────────────────────────────


class TestRunRetrievalEval:
    async def test_scores_hint_gated_and_cross_document_examples(self) -> None:
        runs = InMemoryEvalRunRepository()
        run = await _retrieval_eval(FakeRetrieve(CONTEXTS), runs)()
        # ex1: recall 1.0 (a.pdf at rank 2), rr 0.5; ex2: recall 0.5, rr 1.0.
        assert run.metrics["recall_at_k"] == pytest.approx(0.75)
        assert run.metrics["mrr"] == pytest.approx(0.75)
        assert run.metrics["examples"] == 2.0

    async def test_persists_run_with_config_and_version(self) -> None:
        runs = InMemoryEvalRunRepository()
        run = await _retrieval_eval(FakeRetrieve(CONTEXTS), runs)()
        assert runs.runs == [run]
        assert run.dataset_version == "golden_test"
        assert run.config == {"reranker": "none", "k": "3"}

    async def test_call_time_k_overrides_default(self) -> None:
        runs = InMemoryEvalRunRepository()
        run = await _retrieval_eval(FakeRetrieve(CONTEXTS), runs)(k=1)
        # k=1: ex1 top chunk is a miss (recall 0); ex2 finds a.pdf only (0.5).
        assert run.metrics["recall_at_k"] == pytest.approx(0.25)
        assert run.metrics["mrr"] == pytest.approx(0.5)
        assert run.config["k"] == "1"

    async def test_non_positive_k_rejected(self) -> None:
        eval_run = _retrieval_eval(FakeRetrieve(CONTEXTS), InMemoryEvalRunRepository())
        with pytest.raises(InvalidInputError):
            await eval_run(k=0)

    async def test_queries_use_the_golden_questions(self) -> None:
        retrieve = FakeRetrieve(CONTEXTS)
        await _retrieval_eval(retrieve, InMemoryEvalRunRepository())()
        assert [q.text for q in retrieve.queries] == ["q1", "q2"]


# ── RunJudgeEval ─────────────────────────────────────────────────────────────


def _judge_eval(
    judge: FakeJudge, retrieve: FakeRetrieve, runs: InMemoryEvalRunRepository
) -> RunJudgeEval:
    return RunJudgeEval(
        judge=judge,
        retrieve=retrieve,  # type: ignore[arg-type]  # structural fake
        runs=runs,
        dataset_loader=_loader,
        dataset_version="golden_test",
        config={"judge_model": "fake/judge"},
    )


def _verdict(faithfulness: float, relevancy: float) -> str:
    return json.dumps(
        {"faithfulness": faithfulness, "relevancy": relevancy, "reasoning": "because"}
    )


class TestRunJudgeEval:
    async def test_aggregates_mean_scores_with_judge_suffix(self) -> None:
        judge = FakeJudge([_verdict(0.8, 1.0), _verdict(0.9, 0.5)])
        runs = InMemoryEvalRunRepository()
        run = await _judge_eval(judge, FakeRetrieve(CONTEXTS), runs)()
        assert run.dataset_version == "golden_test-judge"
        assert run.metrics["faithfulness"] == pytest.approx(0.85)
        assert run.metrics["relevancy"] == pytest.approx(0.75)
        assert run.metrics["examples"] == 2.0
        assert runs.runs == [run]

    async def test_judge_prompt_carries_contexts_at_temperature_zero(self) -> None:
        judge = FakeJudge([_verdict(1.0, 1.0), _verdict(1.0, 1.0)])
        await _judge_eval(judge, FakeRetrieve(CONTEXTS), InMemoryEvalRunRepository())()
        first = judge.requests[0]
        assert first.temperature == 0.0
        assert first.messages[0].role == "system"
        assert "mentions ALPHA topic" in first.messages[1].content
        assert "ref1" in first.messages[1].content

    async def test_malformed_verdict_fails_run_and_persists_nothing(self) -> None:
        judge = FakeJudge(["not json at all", _verdict(1.0, 1.0)])
        runs = InMemoryEvalRunRepository()
        with pytest.raises(InvalidInputError, match="ex1"):
            await _judge_eval(judge, FakeRetrieve(CONTEXTS), runs)()
        assert runs.runs == []

    async def test_empty_dataset_rejected(self) -> None:
        eval_run = RunJudgeEval(
            judge=FakeJudge([]),
            retrieve=FakeRetrieve(CONTEXTS),  # type: ignore[arg-type]
            runs=InMemoryEvalRunRepository(),
            dataset_loader=tuple,
            dataset_version="golden_test",
            config={},
        )
        with pytest.raises(InvalidInputError, match="empty"):
            await eval_run()


# ── ListEvalRuns ─────────────────────────────────────────────────────────────


class TestListEvalRuns:
    async def test_returns_recent_runs_up_to_limit(self) -> None:
        runs = InMemoryEvalRunRepository()
        produced = await _retrieval_eval(FakeRetrieve(CONTEXTS), runs)()
        listed = await ListEvalRuns(runs=runs)(limit=1)
        assert listed == [produced]

    async def test_non_positive_limit_rejected(self) -> None:
        with pytest.raises(InvalidInputError):
            await ListEvalRuns(runs=InMemoryEvalRunRepository())(limit=0)


# ── Abstention ───────────────────────────────────────────────────────────────

NEGATIVE = GoldenExample(
    id="neg1",
    question="q3",
    reference_answer="the corpus does not cover this",
    source_files=(),
    answerable=False,
)

MIXED_EXAMPLES = (*EXAMPLES, NEGATIVE)
MIXED_CONTEXTS = {**CONTEXTS, "q3": _context(_chunk("a.pdf", text="unrelated"))}


def _mixed_loader() -> tuple[GoldenExample, ...]:
    return MIXED_EXAMPLES


def _abstention_eval(
    answerer: FakeJudge, runs: InMemoryEvalRunRepository, loader: object = _mixed_loader
) -> RunAbstentionEval:
    return RunAbstentionEval(
        answerer=answerer,  # type: ignore[arg-type]  # structural fake
        retrieve=FakeRetrieve(MIXED_CONTEXTS),  # type: ignore[arg-type]
        runs=runs,
        dataset_loader=loader,  # type: ignore[arg-type]
        dataset_version="golden_test",
        config={"answer_model": "fake/model"},
    )


class TestRunAbstentionEval:
    async def test_perfect_run_answers_positives_and_declines_negative(self) -> None:
        runs = InMemoryEvalRunRepository()
        answerer = FakeJudge(
            [
                "AAL2 needs two factors.",
                "Audit retention is set by policy.",
                "The context does not contain that information.",
            ]
        )
        run = await _abstention_eval(answerer, runs)()
        assert run.metrics["abstention_recall"] == 1.0
        assert run.metrics["false_abstention_rate"] == 0.0
        assert run.metrics["negatives"] == 1.0
        assert run.metrics["positives"] == 2.0
        assert run.dataset_version == "golden_test-abstention"
        assert runs.runs == [run]

    async def test_answering_a_negative_scores_zero_recall(self) -> None:
        """The failure that matters: a confident answer to an unanswerable question."""
        runs = InMemoryEvalRunRepository()
        answerer = FakeJudge(["a1", "a2", "HIPAA requires safeguards for PHI."])
        run = await _abstention_eval(answerer, runs)()
        assert run.metrics["abstention_recall"] == 0.0

    async def test_over_abstention_is_penalised_separately(self) -> None:
        runs = InMemoryEvalRunRepository()
        answerer = FakeJudge(
            ["The context does not contain that.", "a2", "The context does not contain that."]
        )
        run = await _abstention_eval(answerer, runs)()
        assert run.metrics["abstention_recall"] == 1.0
        assert run.metrics["false_abstention_rate"] == 0.5

    async def test_empty_dataset_rejected(self) -> None:
        with pytest.raises(InvalidInputError, match="empty"):
            await _abstention_eval(FakeJudge([]), InMemoryEvalRunRepository(), lambda: ())()

    async def test_dataset_without_negatives_rejected(self) -> None:
        """Only-answerable datasets make the metric vacuous — fail loudly instead."""
        with pytest.raises(InvalidInputError, match="unanswerable"):
            await _abstention_eval(FakeJudge([]), InMemoryEvalRunRepository(), _loader)()

    async def test_prompt_carries_numbered_contexts_and_eval_tags(self) -> None:
        runs = InMemoryEvalRunRepository()
        answerer = FakeJudge(["a1", "a2", "does not contain"])
        await _abstention_eval(answerer, runs)()
        first = answerer.requests[0]
        assert first.temperature == 0.0
        assert first.tags == ("eval", "abstention")
        assert "[1]" in first.messages[1].content
        assert "Question: q1" in first.messages[1].content

    async def test_empty_retrieval_is_reported_to_the_model(self) -> None:
        runs = InMemoryEvalRunRepository()
        answerer = FakeJudge(["does not contain"])
        evaluator = RunAbstentionEval(
            answerer=answerer,  # type: ignore[arg-type]
            retrieve=FakeRetrieve({"q3": _context()}),  # type: ignore[arg-type]
            runs=runs,
            dataset_loader=lambda: (NEGATIVE,),
            dataset_version="golden_test",
            config={},
        )
        await evaluator()
        assert "no passages were retrieved" in answerer.requests[0].messages[1].content


class TestRetrievalEvalSkipsNegatives:
    async def test_negatives_are_excluded_from_rank_metrics(self) -> None:
        """Rank metrics are undefined without source files; negatives would
        otherwise drag recall toward zero and make the gate meaningless."""
        runs = InMemoryEvalRunRepository()
        evaluator = RunRetrievalEval(
            retrieve=FakeRetrieve(MIXED_CONTEXTS),  # type: ignore[arg-type]
            runs=runs,
            dataset_loader=_mixed_loader,
            k=3,
            dataset_version="golden_test",
            config={},
        )
        run = await evaluator()
        # Only the 2 answerable examples are scored, not all 3.
        assert run.metrics["examples"] == 2.0

    async def test_dataset_of_only_negatives_rejected(self) -> None:
        runs = InMemoryEvalRunRepository()
        evaluator = RunRetrievalEval(
            retrieve=FakeRetrieve(MIXED_CONTEXTS),  # type: ignore[arg-type]
            runs=runs,
            dataset_loader=lambda: (NEGATIVE,),
            k=3,
            dataset_version="golden_test",
            config={},
        )
        with pytest.raises(InvalidInputError, match="no answerable examples"):
            await evaluator()


class TestJudgeModelIsPinned:
    async def test_resolved_judge_model_recorded_on_the_run(self) -> None:
        """The judge is part of the eval's definition: the same suite can pass
        under one judge and fail under another, so the run must record which
        model actually produced the verdicts."""
        runs = InMemoryEvalRunRepository()
        judge = FakeJudge(['{"faithfulness": 1.0, "relevancy": 1.0, "reasoning": "ok"}'] * 2)
        evaluator = RunJudgeEval(
            judge=judge,  # type: ignore[arg-type]
            retrieve=FakeRetrieve(CONTEXTS),  # type: ignore[arg-type]
            runs=runs,
            dataset_loader=_loader,
            dataset_version="golden_test",
            config={"judge_model": "requested/model"},
        )
        run = await evaluator()
        # What was asked for, and what actually answered — both recorded.
        assert run.config["judge_model"] == "requested/model"
        assert run.config["judge_model_resolved"] == "fake/judge"


class TestJudgeRetriesEmptyVerdicts:
    """Reasoning models sometimes spend the whole token budget thinking and
    return nothing. One retry covers that tail without averaging away real
    disagreement."""

    _VERDICT = '{"faithfulness": 1.0, "relevancy": 1.0, "reasoning": "ok"}'

    async def test_empty_response_is_retried_once_and_succeeds(self) -> None:
        runs = InMemoryEvalRunRepository()
        # ex1 comes back empty first, then valid; ex2 is valid immediately.
        judge = FakeJudge(["", self._VERDICT, self._VERDICT])
        evaluator = RunJudgeEval(
            judge=judge,  # type: ignore[arg-type]
            retrieve=FakeRetrieve(CONTEXTS),  # type: ignore[arg-type]
            runs=runs,
            dataset_loader=_loader,
            dataset_version="golden_test",
            config={},
        )
        run = await evaluator()
        assert run.metrics["examples"] == 2.0
        assert len(judge.requests) == 3, "the empty verdict should cost one extra call"

    async def test_two_empty_responses_still_fail_loudly(self) -> None:
        """A retry must not become a way to paper over a truncating judge."""
        judge = FakeJudge(["", ""])
        evaluator = RunJudgeEval(
            judge=judge,  # type: ignore[arg-type]
            retrieve=FakeRetrieve(CONTEXTS),  # type: ignore[arg-type]
            runs=InMemoryEvalRunRepository(),
            dataset_loader=_loader,
            dataset_version="golden_test",
            config={},
        )
        with pytest.raises(InvalidInputError, match="empty response"):
            await evaluator()

    async def test_a_valid_verdict_is_never_retried(self) -> None:
        """Only the empty case retries — verdicts are not sampled or averaged."""
        judge = FakeJudge([self._VERDICT, self._VERDICT])
        evaluator = RunJudgeEval(
            judge=judge,  # type: ignore[arg-type]
            retrieve=FakeRetrieve(CONTEXTS),  # type: ignore[arg-type]
            runs=InMemoryEvalRunRepository(),
            dataset_loader=_loader,
            dataset_version="golden_test",
            config={},
        )
        await evaluator()
        assert len(judge.requests) == 2


class TestJudgeEvalSkipsNegatives:
    """The judge rubric asks whether the reference answer's claims are supported
    by the retrieved passages. A negative's reference answer is a refusal, so
    the question is not well-posed — measured, the judge returned
    0.0/1.0/0.0/1.0/1.0 on the five negatives, which is noise in the mean."""

    _VERDICT = '{"faithfulness": 1.0, "relevancy": 1.0, "reasoning": "ok"}'

    async def test_negatives_are_not_judged(self) -> None:
        runs = InMemoryEvalRunRepository()
        judge = FakeJudge([self._VERDICT, self._VERDICT])  # only 2, not 3
        evaluator = RunJudgeEval(
            judge=judge,  # type: ignore[arg-type]
            retrieve=FakeRetrieve(MIXED_CONTEXTS),  # type: ignore[arg-type]
            runs=runs,
            dataset_loader=_mixed_loader,
            dataset_version="golden_test",
            config={},
        )
        run = await evaluator()
        assert run.metrics["examples"] == 2.0
        assert len(judge.requests) == 2, "the negative must never reach the judge"

    async def test_dataset_of_only_negatives_rejected(self) -> None:
        evaluator = RunJudgeEval(
            judge=FakeJudge([]),  # type: ignore[arg-type]
            retrieve=FakeRetrieve(MIXED_CONTEXTS),  # type: ignore[arg-type]
            runs=InMemoryEvalRunRepository(),
            dataset_loader=lambda: (NEGATIVE,),
            dataset_version="golden_test",
            config={},
        )
        with pytest.raises(InvalidInputError, match="no answerable examples"):
            await evaluator()
