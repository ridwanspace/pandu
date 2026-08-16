"""Golden JSONL parsing and validation."""

from __future__ import annotations

import json

import pytest

from app.modules.evaluation.domain.dataset import parse_golden_jsonl
from app.shared.domain.errors import InvalidInputError


def _line(**overrides: object) -> str:
    payload: dict[str, object] = {
        "id": "q1",
        "question": "What is AAL2?",
        "reference_answer": "An authenticator assurance level.",
        "source_files": ["nist-sp-800-63b.pdf"],
        "source_hints": ["AAL2"],
    }
    payload.update(overrides)
    return json.dumps(payload)


class TestParseGoldenJsonl:
    def test_parses_examples_and_skips_blank_lines(self) -> None:
        examples = parse_golden_jsonl([_line(), "", "   \n", _line(id="q2")])
        assert [e.id for e in examples] == ["q1", "q2"]
        assert examples[0].source_files == ("nist-sp-800-63b.pdf",)
        assert examples[0].source_hints == ("AAL2",)

    def test_source_hints_are_optional(self) -> None:
        raw = json.loads(_line())
        del raw["source_hints"]
        (example,) = parse_golden_jsonl([json.dumps(raw)])
        assert example.source_hints == ()

    def test_invalid_json_reports_line_number(self) -> None:
        with pytest.raises(InvalidInputError, match="line 2"):
            parse_golden_jsonl([_line(), "{not json"])

    def test_non_object_line_rejected(self) -> None:
        with pytest.raises(InvalidInputError, match=r"line 1.*object"):
            parse_golden_jsonl(['["a", "list"]'])

    def test_duplicate_ids_rejected(self) -> None:
        with pytest.raises(InvalidInputError, match=r"line 3.*duplicate id 'q1'"):
            parse_golden_jsonl([_line(), "", _line()])

    @pytest.mark.parametrize("field", ["id", "question", "reference_answer"])
    def test_empty_string_fields_rejected(self, field: str) -> None:
        with pytest.raises(InvalidInputError, match=f"line 1.*{field}"):
            parse_golden_jsonl([_line(**{field: "  "})])

    def test_missing_source_files_rejected(self) -> None:
        raw = json.loads(_line())
        del raw["source_files"]
        with pytest.raises(InvalidInputError, match="source_files"):
            parse_golden_jsonl([json.dumps(raw)])

    def test_empty_source_files_rejected(self) -> None:
        with pytest.raises(InvalidInputError, match="source_files"):
            parse_golden_jsonl([_line(source_files=[])])

    def test_non_string_source_file_rejected(self) -> None:
        with pytest.raises(InvalidInputError, match="source_files"):
            parse_golden_jsonl([_line(source_files=["ok.pdf", 3])])

    def test_values_are_stripped(self) -> None:
        (example,) = parse_golden_jsonl([_line(id="  q1  ", source_files=[" a.pdf "])])
        assert example.id == "q1"
        assert example.source_files == ("a.pdf",)
