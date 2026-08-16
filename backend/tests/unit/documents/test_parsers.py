"""Parser adapters: markdown structure, routing, and the missing-docling path."""

from __future__ import annotations

import importlib.util

import pytest

from app.modules.documents.domain.parser import BlockKind, ParsedBlock
from app.modules.documents.infrastructure.parsers import (
    CompositeParser,
    DoclingParser,
    PlainTextParser,
    build_default_parser,
)
from app.shared.domain.errors import InvalidInputError

DOCLING_INSTALLED = importlib.util.find_spec("docling") is not None

MARKDOWN = """\
# Title

Intro paragraph
continues here.

## Section One

Para one.

- item one
- item two

```python
code line one
code line two
```

| a | b |
| 1 | 2 |

## Section Two

Final.
"""


def parse_markdown(text: str) -> tuple[ParsedBlock, ...]:
    parser = PlainTextParser()
    return parser.parse(text.encode(), filename="doc.md", content_type="text/markdown").blocks


class TestPlainTextParser:
    def test_supports_text_types_and_extensions(self) -> None:
        parser = PlainTextParser()
        assert parser.supports("text/plain", "notes.txt")
        assert parser.supports("text/markdown", "readme.md")
        assert parser.supports("application/octet-stream", "readme.md")
        assert not parser.supports("application/pdf", "doc.pdf")

    def test_headings_become_heading_paths_not_blocks(self) -> None:
        blocks = parse_markdown(MARKDOWN)
        assert all(b.kind is not BlockKind.HEADING for b in blocks)
        assert blocks[0].heading_path == ("Title",)
        assert blocks[1].heading_path == ("Title", "Section One")
        assert blocks[-1].heading_path == ("Title", "Section Two")

    def test_soft_wrapped_paragraph_is_one_block(self) -> None:
        blocks = parse_markdown(MARKDOWN)
        assert blocks[0].kind is BlockKind.TEXT
        assert blocks[0].text == "Intro paragraph continues here."

    def test_list_items_are_individual_blocks(self) -> None:
        blocks = parse_markdown(MARKDOWN)
        list_items = [b for b in blocks if b.kind is BlockKind.LIST_ITEM]
        assert [b.text for b in list_items] == ["- item one", "- item two"]

    def test_fenced_code_becomes_code_block(self) -> None:
        blocks = parse_markdown(MARKDOWN)
        code = [b for b in blocks if b.kind is BlockKind.CODE]
        assert len(code) == 1
        assert code[0].text == "code line one\ncode line two"

    def test_pipe_table_becomes_table_block(self) -> None:
        blocks = parse_markdown(MARKDOWN)
        tables = [b for b in blocks if b.kind is BlockKind.TABLE]
        assert len(tables) == 1
        assert tables[0].text == "| a | b |\n| 1 | 2 |"

    def test_heading_level_jump_truncates_trail(self) -> None:
        blocks = parse_markdown("# A\n\n### Deep\n\ntext\n\n## B\n\nmore\n")
        assert blocks[0].heading_path == ("A", "Deep")
        assert blocks[1].heading_path == ("A", "B")

    def test_unterminated_fence_keeps_content(self) -> None:
        blocks = parse_markdown("```\norphan code\n")
        assert blocks[0].kind is BlockKind.CODE
        assert blocks[0].text == "orphan code"

    def test_plain_text_without_markdown(self) -> None:
        blocks = parse_markdown("just a paragraph\n\nand another one\n")
        assert [b.text for b in blocks] == ["just a paragraph", "and another one"]
        assert all(b.heading_path == () for b in blocks)


class TestDoclingParser:
    def test_supports_pdf_only(self) -> None:
        parser = DoclingParser()
        assert parser.supports("application/pdf", "report.pdf")
        assert parser.supports("application/octet-stream", "report.PDF")
        assert not parser.supports("text/plain", "notes.txt")

    @pytest.mark.skipif(DOCLING_INSTALLED, reason="docling extra is installed here")
    def test_missing_docling_raises_with_install_hint(self) -> None:
        parser = DoclingParser()
        with pytest.raises(InvalidInputError, match=r"uv sync --extra parsing"):
            parser.parse(b"%PDF-1.4", filename="report.pdf", content_type="application/pdf")


class TestCompositeParser:
    def test_routes_to_first_supporting_parser(self) -> None:
        composite = CompositeParser((DoclingParser(), PlainTextParser()))
        parsed = composite.parse(b"hello there", filename="a.txt", content_type="text/plain")
        assert parsed.blocks[0].text == "hello there"

    def test_supports_union_of_adapters(self) -> None:
        composite = build_default_parser()
        assert composite.supports("application/pdf", "a.pdf")
        assert composite.supports("text/markdown", "a.md")
        assert not composite.supports("application/zip", "a.zip")

    def test_unsupported_type_raises(self) -> None:
        composite = build_default_parser()
        with pytest.raises(InvalidInputError, match="no parser supports"):
            composite.parse(b"zip!", filename="a.zip", content_type="application/zip")
