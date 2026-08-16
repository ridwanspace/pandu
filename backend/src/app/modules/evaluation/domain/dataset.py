"""Golden-set JSONL parsing — pure, stdlib-only.

One JSON object per line; blank lines are ignored. Every error carries the
1-based line number so a bad edit to the golden file fails loudly in CI with
an actionable message, not a stack trace deep inside an eval run.
"""

from __future__ import annotations

import json
from collections.abc import Iterable

from app.modules.evaluation.domain.entities import GoldenExample
from app.shared.domain.errors import InvalidInputError


def parse_golden_jsonl(lines: Iterable[str]) -> tuple[GoldenExample, ...]:
    """Parse and validate a golden dataset.

    Enforced invariants: valid JSON objects; non-empty ``id``, ``question``,
    ``reference_answer``; at least one non-empty ``source_files`` entry;
    ``source_hints`` (optional) all non-empty strings; ids unique across the
    file. Violations raise :class:`InvalidInputError` with the line number.
    """
    examples: list[GoldenExample] = []
    seen_ids: set[str] = set()
    for line_no, raw in enumerate(lines, start=1):
        line = raw.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            raise InvalidInputError(f"golden line {line_no}: invalid JSON ({exc.msg})") from exc
        if not isinstance(obj, dict):
            raise InvalidInputError(f"golden line {line_no}: expected a JSON object")
        example = GoldenExample(
            id=_required_str(obj, "id", line_no),
            question=_required_str(obj, "question", line_no),
            reference_answer=_required_str(obj, "reference_answer", line_no),
            source_files=_str_tuple(obj, "source_files", line_no, required=True),
            source_hints=_str_tuple(obj, "source_hints", line_no, required=False),
        )
        if example.id in seen_ids:
            raise InvalidInputError(f"golden line {line_no}: duplicate id {example.id!r}")
        seen_ids.add(example.id)
        examples.append(example)
    return tuple(examples)


def _required_str(obj: dict[str, object], key: str, line_no: int) -> str:
    value = obj.get(key)
    if not isinstance(value, str) or not value.strip():
        raise InvalidInputError(f"golden line {line_no}: {key!r} must be a non-empty string")
    return value.strip()


def _str_tuple(
    obj: dict[str, object], key: str, line_no: int, *, required: bool
) -> tuple[str, ...]:
    value = obj.get(key)
    if value is None:
        if required:
            raise InvalidInputError(f"golden line {line_no}: {key!r} is required")
        return ()
    if not isinstance(value, list) or any(not isinstance(v, str) or not v.strip() for v in value):
        raise InvalidInputError(
            f"golden line {line_no}: {key!r} must be a list of non-empty strings"
        )
    if required and not value:
        raise InvalidInputError(f"golden line {line_no}: {key!r} must not be empty")
    return tuple(v.strip() for v in value)
