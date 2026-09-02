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
    ``reference_answer``; ``source_hints`` (optional) all non-empty strings;
    ids unique across the file. Violations raise :class:`InvalidInputError`
    with the line number.

    ``answerable`` (optional, default ``True``) marks negatives. The
    ``source_files`` rule is conditional on it, and the two directions are
    both enforced because either mistake silently corrupts the metrics:
    an answerable example MUST list at least one source file (otherwise
    recall is undefined for it), and a negative MUST list none (a negative
    with sources is a labelling error that would score as a retrieval miss
    forever).
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
        answerable = _optional_bool(obj, "answerable", line_no, default=True)
        source_files = _str_tuple(obj, "source_files", line_no, required=answerable)
        if not answerable and source_files:
            raise InvalidInputError(
                f"golden line {line_no}: an unanswerable example must not list 'source_files'"
            )
        example = GoldenExample(
            id=_required_str(obj, "id", line_no),
            question=_required_str(obj, "question", line_no),
            reference_answer=_required_str(obj, "reference_answer", line_no),
            source_files=source_files,
            source_hints=_str_tuple(obj, "source_hints", line_no, required=False),
            answerable=answerable,
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


def _optional_bool(obj: dict[str, object], key: str, line_no: int, *, default: bool) -> bool:
    value = obj.get(key)
    if value is None:
        return default
    if not isinstance(value, bool):
        raise InvalidInputError(f"golden line {line_no}: {key!r} must be a boolean")
    return value
