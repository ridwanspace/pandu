"""Document parsing port.

Docling is the default adapter (ADR-004); the port keeps Unstructured /
LlamaParse adapters possible and lets tests use a lightweight text parser.
Parsing is synchronous CPU-bound work — the worker offloads it to a thread.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class BlockKind(StrEnum):
    HEADING = "heading"
    TEXT = "text"
    TABLE = "table"
    LIST_ITEM = "list_item"
    CODE = "code"


@dataclass(frozen=True, slots=True)
class ParsedBlock:
    kind: BlockKind
    text: str
    # Heading trail leading to this block, e.g. ("3 Access Control", "3.1 MFA").
    heading_path: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ParsedDocument:
    blocks: tuple[ParsedBlock, ...]


class DocumentParser(Protocol):
    def supports(self, content_type: str, filename: str) -> bool: ...

    def parse(self, content: bytes, *, filename: str, content_type: str) -> ParsedDocument: ...
