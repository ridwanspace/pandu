"""LLM-as-judge rubric — pure prompt construction and strict verdict parsing.

The judge scores (question, reference answer, retrieved contexts) on two axes:

- ``faithfulness``: are the reference answer's claims supported by the
  retrieved contexts? Low faithfulness with a correct reference answer means
  retrieval fetched the wrong passages — the metric targets the pipeline, not
  the hand-written answer.
- ``relevancy``: are the contexts sufficient and on-topic to answer the
  question at all (answerability)?

Parsing is strict on purpose: a judge that emits malformed JSON must fail the
example loudly rather than silently score 0 — silent zeros poison threshold
trends.
"""

from __future__ import annotations

import json

from app.modules.evaluation.domain.entities import JudgeVerdict
from app.shared.domain.errors import InvalidInputError

JUDGE_SYSTEM_PROMPT = (
    "You are a strict evaluation judge for a retrieval-augmented generation system. "
    "You will receive a question, a human-written reference answer, and the passages a "
    "retrieval pipeline fetched for that question. Score the retrieved passages on two axes, "
    "each a number between 0.0 and 1.0:\n"
    "- faithfulness: the fraction of the reference answer's factual claims that are "
    "supported by the passages. 1.0 means every claim is grounded; 0.0 means none are.\n"
    "- relevancy: how sufficient and on-topic the passages are for answering the question "
    "at all. 1.0 means the question is fully answerable from the passages alone.\n"
    "Respond with a single JSON object and nothing else, exactly this shape:\n"
    '{"faithfulness": <float>, "relevancy": <float>, "reasoning": "<one or two sentences>"}'
)


def build_judge_prompt(
    *,
    question: str,
    reference_answer: str,
    contexts: tuple[str, ...],
) -> str:
    """Assemble the user message for one judged example."""
    numbered = "\n\n".join(
        f"[context {index}]\n{text}" for index, text in enumerate(contexts, start=1)
    )
    if not numbered:
        numbered = "(no passages were retrieved)"
    return (
        f"Question:\n{question}\n\n"
        f"Reference answer:\n{reference_answer}\n\n"
        f"Retrieved passages:\n{numbered}"
    )


def parse_verdict(example_id: str, raw: str) -> JudgeVerdict:
    """Parse a judge completion into a :class:`JudgeVerdict`.

    Accepts an optional markdown code fence around the JSON (a common LLM
    habit even when told not to); everything else is strict. Malformed output,
    non-numeric or out-of-range scores raise :class:`InvalidInputError`.

    The empty-response case gets its own message because it has one dominant
    cause and a non-obvious fix: reasoning models spend completion budget on
    hidden thinking *before* emitting the answer, so a ``max_output_tokens``
    that looks generous can be consumed entirely by reasoning, leaving no
    verdict at all. Reported as "invalid JSON" it masquerades as judge
    flakiness — and averaging repeated runs makes it worse, not better,
    because every repeat truncates the same way.
    """
    text = _strip_code_fence(raw.strip())
    if not text:
        raise InvalidInputError(
            f"judge verdict for {example_id!r}: the judge returned an empty response. "
            "Reasoning models consume max_output_tokens on hidden reasoning before "
            "emitting the verdict — raise max_output_tokens, or pin a judge that "
            "does not reason."
        )
    try:
        obj = json.loads(text)
    except json.JSONDecodeError as exc:
        raise InvalidInputError(f"judge verdict for {example_id!r}: invalid JSON") from exc
    if not isinstance(obj, dict):
        raise InvalidInputError(f"judge verdict for {example_id!r}: expected a JSON object")
    reasoning = obj.get("reasoning", "")
    if not isinstance(reasoning, str):
        raise InvalidInputError(f"judge verdict for {example_id!r}: 'reasoning' must be a string")
    return JudgeVerdict(
        example_id=example_id,
        faithfulness=_score(obj, "faithfulness", example_id),
        relevancy=_score(obj, "relevancy", example_id),
        reasoning=reasoning,
    )


def _strip_code_fence(text: str) -> str:
    if not text.startswith("```"):
        return text
    lines = text.splitlines()
    if len(lines) >= 2 and lines[-1].strip() == "```":
        return "\n".join(lines[1:-1]).strip()
    return text


def _score(obj: dict[str, object], key: str, example_id: str) -> float:
    value = obj.get(key)
    # bool is an int subclass; a judge answering true/false is malformed here.
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise InvalidInputError(f"judge verdict for {example_id!r}: {key!r} must be a number")
    score = float(value)
    if not 0.0 <= score <= 1.0:
        raise InvalidInputError(
            f"judge verdict for {example_id!r}: {key!r} must be within [0, 1], got {score}"
        )
    return score
