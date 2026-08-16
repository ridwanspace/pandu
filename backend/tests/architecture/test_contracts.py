"""Architecture tests: the import-linter contracts from pyproject.toml, run as
part of the test suite so a broken boundary fails `pytest` too, not just CI's
dedicated lint-imports step."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]


def test_import_linter_contracts() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "importlinter.cli", "lint_imports"],
        cwd=BACKEND_DIR,
        capture_output=True,
        text=True,
        check=False,
    )
    detail = f"architecture contracts broken:\n{result.stdout}\n{result.stderr}"
    assert result.returncode == 0, detail


def test_domain_layers_have_no_framework_imports() -> None:
    """Belt-and-braces textual check: no framework/SDK import statements in any
    domain layer (import-linter checks the import graph; this catches strings
    like lazy imports inside functions too)."""
    banned = (
        "import fastapi",
        "from fastapi",
        "import sqlalchemy",
        "from sqlalchemy",
        "import pydantic",
        "from pydantic",
        "import openai",
        "from openai",
        "from google",
        "import httpx",
        "from httpx",
    )
    src = BACKEND_DIR / "src" / "app"
    domain_files = [p for p in src.rglob("*.py") if "domain" in p.relative_to(src).parts]
    assert domain_files, "no domain files found — layout changed?"
    offenders: list[str] = []
    for path in domain_files:
        text = path.read_text(encoding="utf-8")
        for line in text.splitlines():
            stripped = line.strip()
            if any(stripped.startswith(b) for b in banned):
                offenders.append(f"{path}: {stripped}")
    assert not offenders, "framework imports in domain layer:\n" + "\n".join(offenders)
