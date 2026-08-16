"""Judge prompt construction and strict verdict parsing."""

from __future__ import annotations

import pytest

from app.modules.evaluation.domain.judging import build_judge_prompt, parse_verdict
from app.shared.domain.errors import InvalidInputError


class TestBuildJudgePrompt:
    def test_contains_question_answer_and_numbered_contexts(self) -> None:
        prompt = build_judge_prompt(
            question="What is AAL2?",
            reference_answer="Two factors.",
            contexts=("first passage", "second passage"),
        )
        assert "What is AAL2?" in prompt
        assert "Two factors." in prompt
        assert "[context 1]\nfirst passage" in prompt
        assert "[context 2]\nsecond passage" in prompt

    def test_empty_contexts_are_explicit(self) -> None:
        prompt = build_judge_prompt(question="q", reference_answer="a", contexts=())
        assert "no passages were retrieved" in prompt


class TestParseVerdict:
    def test_valid_json(self) -> None:
        verdict = parse_verdict(
            "q1", '{"faithfulness": 0.9, "relevancy": 1, "reasoning": "grounded"}'
        )
        assert verdict.example_id == "q1"
        assert verdict.faithfulness == 0.9
        assert verdict.relevancy == 1.0
        assert verdict.reasoning == "grounded"

    def test_markdown_fenced_json_accepted(self) -> None:
        raw = '```json\n{"faithfulness": 0.5, "relevancy": 0.25, "reasoning": ""}\n```'
        verdict = parse_verdict("q1", raw)
        assert verdict.faithfulness == 0.5
        assert verdict.relevancy == 0.25

    def test_reasoning_is_optional(self) -> None:
        verdict = parse_verdict("q1", '{"faithfulness": 0.1, "relevancy": 0.2}')
        assert verdict.reasoning == ""

    def test_non_string_reasoning_rejected(self) -> None:
        with pytest.raises(InvalidInputError, match="reasoning"):
            parse_verdict("q1", '{"faithfulness": 0.9, "relevancy": 0.8, "reasoning": 42}')

    def test_unterminated_code_fence_is_not_stripped(self) -> None:
        # No closing fence: the text passes through verbatim and fails as JSON.
        with pytest.raises(InvalidInputError, match="invalid JSON"):
            parse_verdict("q1", '```json\n{"faithfulness": 0.9, "relevancy": 0.8}')

    def test_malformed_json_raises_with_example_id(self) -> None:
        with pytest.raises(InvalidInputError, match="q7"):
            parse_verdict("q7", "the contexts look fine to me")

    def test_non_object_rejected(self) -> None:
        with pytest.raises(InvalidInputError, match="object"):
            parse_verdict("q1", "[0.9, 0.8]")

    def test_missing_score_rejected(self) -> None:
        with pytest.raises(InvalidInputError, match="relevancy"):
            parse_verdict("q1", '{"faithfulness": 0.9, "reasoning": "x"}')

    def test_non_numeric_score_rejected(self) -> None:
        with pytest.raises(InvalidInputError, match="faithfulness"):
            parse_verdict("q1", '{"faithfulness": "high", "relevancy": 0.5}')

    def test_boolean_score_rejected(self) -> None:
        with pytest.raises(InvalidInputError, match="faithfulness"):
            parse_verdict("q1", '{"faithfulness": true, "relevancy": 0.5}')

    @pytest.mark.parametrize("value", ["-0.1", "1.5"])
    def test_out_of_range_score_rejected(self, value: str) -> None:
        with pytest.raises(InvalidInputError, match="within"):
            parse_verdict("q1", f'{{"faithfulness": {value}, "relevancy": 0.5}}')
