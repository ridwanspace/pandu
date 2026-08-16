"""Optional ragas generation-metric suite over the golden set.

ragas lives in the ``eval`` dependency group (``uv run --group eval ...``);
without it this module prints a clear skip message and returns ``None`` rather
than failing — generation metrics are an opt-in, token-costing layer on top of
the always-on retrieval metrics.

Honest limitations, on purpose kept visible instead of papered over:

- Answers are generated here with a minimal grounded prompt (retrieved
  contexts + question) because the eval harness scores the retrieval+generation
  loop, not the chat UX; the chat module owns the production prompt.
- ragas' ``llm_factory``/default embeddings target OpenAI via langchain, so
  this runner requires an ``openai/...`` judge model and an OpenAI API key.
  Non-OpenAI judges are skipped with a message, not silently mis-scored.
"""

from __future__ import annotations

import math
import os
from typing import TYPE_CHECKING, Any

from app.modules.retrieval.application.dto import RetrievalQuery
from app.shared.domain.ports.llm import ChatMessage, CompletionRequest, LLMProvider

if TYPE_CHECKING:
    from app.modules.evaluation.domain.entities import GoldenExample
    from app.modules.retrieval.application.use_cases import RetrieveContext

RAGAS_METRIC_NAMES = ("faithfulness", "answer_relevancy", "context_precision", "context_recall")

_ANSWER_SYSTEM_PROMPT = (
    "Answer the question using only the provided context passages. "
    "If the passages do not contain the answer, say that the context is insufficient."
)


async def run_ragas(
    *,
    retrieve: RetrieveContext,
    chat: LLMProvider,
    examples: tuple[GoldenExample, ...],
    judge_model: str,
    openai_api_key: str,
) -> dict[str, float] | None:
    """Compute faithfulness / answer relevancy / context precision / recall.

    Returns the mean score per metric, or ``None`` when ragas is unavailable
    or the configured judge cannot drive it.
    """
    try:
        from datasets import Dataset
        from ragas import evaluate
        from ragas.llms import llm_factory
        from ragas.metrics import (
            answer_relevancy,
            context_precision,
            context_recall,
            faithfulness,
        )
    except ImportError:
        print(
            "ragas is not installed — skipping generation metrics. "
            "Run with: uv run --group eval python -m evals.run --ragas"
        )
        return None

    provider, _, model_name = judge_model.partition("/")
    if provider != "openai" or not model_name:
        print(
            f"ragas runner requires an openai/* judge model (got {judge_model!r}) — "
            "skipping generation metrics."
        )
        return None
    if openai_api_key:
        os.environ.setdefault("OPENAI_API_KEY", openai_api_key)

    questions: list[str] = []
    answers: list[str] = []
    contexts: list[list[str]] = []
    ground_truths: list[str] = []
    for example in examples:
        retrieved = await retrieve(RetrievalQuery(text=example.question))
        passages = [chunk.text for chunk in retrieved.chunks]
        questions.append(example.question)
        answers.append(await _generate_answer(chat, example.question, passages))
        contexts.append(passages)
        ground_truths.append(example.reference_answer)

    dataset = Dataset.from_dict(
        {
            "question": questions,
            "answer": answers,
            "contexts": contexts,
            "ground_truth": ground_truths,
        }
    )
    result = evaluate(
        dataset,
        metrics=[faithfulness, answer_relevancy, context_precision, context_recall],
        llm=llm_factory(model=model_name),
    )
    return _mean_scores(result.scores)


async def _generate_answer(chat: LLMProvider, question: str, passages: list[str]) -> str:
    numbered = "\n\n".join(f"[{i}] {text}" for i, text in enumerate(passages, start=1))
    request = CompletionRequest(
        messages=(
            ChatMessage(role="system", content=_ANSWER_SYSTEM_PROMPT),
            ChatMessage(
                role="user",
                content=f"Context passages:\n{numbered}\n\nQuestion: {question}",
            ),
        ),
        temperature=0.0,
        max_output_tokens=512,
        tags=("eval", "ragas"),
    )
    result = await chat.complete(request)
    return result.text


def _mean_scores(rows: Any) -> dict[str, float]:
    """Average per-example ragas scores; NaN rows are dropped per metric so a
    single degenerate example does not blank an entire column."""
    sums: dict[str, float] = {}
    counts: dict[str, int] = {}
    for row in rows:
        for name, value in dict(row).items():
            score = float(value)
            if math.isnan(score):
                continue
            sums[name] = sums.get(name, 0.0) + score
            counts[name] = counts.get(name, 0) + 1
    return {name: sums[name] / counts[name] for name in sums}
