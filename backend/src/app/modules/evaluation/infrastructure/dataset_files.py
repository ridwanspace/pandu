"""File-backed golden dataset loader. The path is injected by the composition
root (API process and eval CLI resolve it differently)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from app.modules.evaluation.domain.dataset import parse_golden_jsonl
from app.modules.evaluation.domain.entities import GoldenExample
from app.shared.domain.errors import NotFoundError


def golden_dataset_loader(path: Path) -> Callable[[], tuple[GoldenExample, ...]]:
    """Build a loader closure over a JSONL golden file.

    Reads lazily on each call so a redeployed dataset is picked up without a
    process restart; parsing revalidates every time, which is cheap at golden
    -set scale and catches bad edits immediately.
    """

    def load() -> tuple[GoldenExample, ...]:
        if not path.is_file():
            raise NotFoundError(f"golden dataset not found: {path}")
        with path.open(encoding="utf-8") as handle:
            return parse_golden_jsonl(handle)

    return load
