"""Parser adapters implementing the ``DocumentParser`` port.

Docling (ADR-004) handles PDFs but pulls torch, so it is an optional extra
imported lazily; text and markdown ingestion works without it.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

from app.modules.documents.domain.parser import (
    BlockKind,
    DocumentParser,
    ParsedBlock,
    ParsedDocument,
)
from app.shared.domain.errors import InvalidInputError

_MARKDOWN_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+\S")
_FENCE = re.compile(r"^\s*(```|~~~)")

_TEXT_CONTENT_TYPES = frozenset({"text/plain", "text/markdown"})
_TEXT_SUFFIXES = (".txt", ".md", ".markdown")


class PlainTextParser:
    """Parses txt/markdown into structured blocks.

    Markdown headings become the ``heading_path`` trail of subsequent blocks
    (they are context, not content), fenced code becomes CODE blocks, pipe
    tables become TABLE blocks, bullet/numbered lines become LIST_ITEM blocks,
    and everything else folds into TEXT paragraphs.
    """

    def supports(self, content_type: str, filename: str) -> bool:
        return content_type in _TEXT_CONTENT_TYPES or filename.lower().endswith(_TEXT_SUFFIXES)

    def parse(self, content: bytes, *, filename: str, content_type: str) -> ParsedDocument:
        text = content.decode("utf-8", errors="replace")
        blocks: list[ParsedBlock] = []
        trail: list[str] = []
        paragraph: list[str] = []
        table: list[str] = []
        code: list[str] = []
        in_code = False
        fence = ""

        def heading_path() -> tuple[str, ...]:
            return tuple(trail)

        def flush_paragraph() -> None:
            if paragraph:
                blocks.append(
                    ParsedBlock(
                        kind=BlockKind.TEXT, text=" ".join(paragraph), heading_path=heading_path()
                    )
                )
                paragraph.clear()

        def flush_table() -> None:
            if table:
                blocks.append(
                    ParsedBlock(
                        kind=BlockKind.TABLE, text="\n".join(table), heading_path=heading_path()
                    )
                )
                table.clear()

        for raw_line in text.splitlines():
            line = raw_line.rstrip()
            if in_code:
                if _FENCE.match(line) and line.strip().startswith(fence):
                    in_code = False
                    if code:
                        blocks.append(
                            ParsedBlock(
                                kind=BlockKind.CODE,
                                text="\n".join(code),
                                heading_path=heading_path(),
                            )
                        )
                        code.clear()
                else:
                    code.append(raw_line)
                continue

            fence_match = _FENCE.match(line)
            if fence_match:
                flush_paragraph()
                flush_table()
                in_code = True
                fence = fence_match.group(1)
                continue

            heading = _MARKDOWN_HEADING.match(line)
            if heading:
                flush_paragraph()
                flush_table()
                level = len(heading.group(1))
                del trail[level - 1 :]
                trail.append(heading.group(2))
                continue

            if not line.strip():
                flush_paragraph()
                flush_table()
                continue

            if line.lstrip().startswith("|"):
                flush_paragraph()
                table.append(line.strip())
                continue

            flush_table()
            if _LIST_ITEM.match(line):
                flush_paragraph()
                blocks.append(
                    ParsedBlock(
                        kind=BlockKind.LIST_ITEM, text=line.strip(), heading_path=heading_path()
                    )
                )
                continue

            paragraph.append(line.strip())

        flush_paragraph()
        flush_table()
        if in_code and code:
            # Unterminated fence: keep the content rather than dropping it.
            blocks.append(
                ParsedBlock(kind=BlockKind.CODE, text="\n".join(code), heading_path=heading_path())
            )
        return ParsedDocument(blocks=tuple(blocks))


class DoclingParser:
    """PDF parsing via Docling, imported lazily (optional heavy extra).

    ``ocr`` defaults to **off**. Docling's default pipeline runs OCR over every
    page, which for a PDF that already has a text layer is pure cost: on the
    NIST seed corpus it turns a parse measured in seconds into one measured in
    tens of minutes and adds nothing, because the extracted text is identical.
    Scanned or image-only PDFs genuinely need it, so it stays available —
    ``DOCLING_OCR=true`` — rather than being removed.
    """

    def __init__(self, *, ocr: bool = False) -> None:
        self._converter: Any = None
        self._ocr = ocr

    def supports(self, content_type: str, filename: str) -> bool:
        return content_type == "application/pdf" or filename.lower().endswith(".pdf")

    def parse(self, content: bytes, *, filename: str, content_type: str) -> ParsedDocument:
        import io

        converter, document_stream = self._load_docling()
        stream = document_stream(name=filename or "upload.pdf", stream=io.BytesIO(content))
        document = converter.convert(stream).document
        return ParsedDocument(blocks=tuple(self._map_items(document)))

    def _load_docling(self) -> tuple[Any, Any]:
        try:
            from docling.datamodel.base_models import DocumentStream
            from docling.document_converter import DocumentConverter
        except ImportError as exc:
            msg = (
                "PDF parsing requires the optional docling dependency; "
                "install it with `uv sync --extra parsing`"
            )
            raise InvalidInputError(msg) from exc
        if self._converter is None:
            self._converter = self._build_converter(DocumentConverter)
        return self._converter, DocumentStream

    def _build_converter(self, document_converter: Any) -> Any:
        """Converter with OCR under our control rather than Docling's default.

        Table structure recognition stays ON: the corpus is control catalogs,
        and the tables are the content.
        """
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import PdfPipelineOptions
        from docling.document_converter import PdfFormatOption

        options = PdfPipelineOptions()
        options.do_ocr = self._ocr
        options.do_table_structure = True
        return document_converter(
            format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)}
        )

    def _map_items(self, document: Any) -> list[ParsedBlock]:
        blocks: list[ParsedBlock] = []
        trail: list[str] = []
        has_title = False
        for item, _level in document.iterate_items():
            label = _label_of(item)
            if label in ("page_header", "page_footer", "picture", "formula"):
                continue
            if label == "title":
                trail[:] = [_text_of(item, document)]
                has_title = True
                continue
            if label == "section_header":
                level = max(1, int(getattr(item, "level", 1) or 1))
                base = 1 if has_title else 0
                del trail[base + level - 1 :]
                trail.append(_text_of(item, document))
                continue
            kind = _KIND_BY_LABEL.get(label, BlockKind.TEXT)
            text = _text_of(item, document)
            if text.strip():
                blocks.append(ParsedBlock(kind=kind, text=text, heading_path=tuple(trail)))
        return blocks


_KIND_BY_LABEL = {
    "table": BlockKind.TABLE,
    "list_item": BlockKind.LIST_ITEM,
    "code": BlockKind.CODE,
    "text": BlockKind.TEXT,
    "paragraph": BlockKind.TEXT,
    "caption": BlockKind.TEXT,
    "footnote": BlockKind.TEXT,
}


def _label_of(item: Any) -> str:
    label = getattr(item, "label", "")
    return str(getattr(label, "value", label))


def _text_of(item: Any, document: Any) -> str:
    if _label_of(item) == "table":
        export = getattr(item, "export_to_markdown", None)
        if callable(export):
            try:
                return str(export(doc=document))
            except TypeError:
                return str(export())
    return str(getattr(item, "text", "") or "")


class CompositeParser:
    """Routes to the first adapter that supports the payload."""

    def __init__(self, parsers: Sequence[DocumentParser]) -> None:
        self._parsers = tuple(parsers)

    def supports(self, content_type: str, filename: str) -> bool:
        return any(p.supports(content_type, filename) for p in self._parsers)

    def parse(self, content: bytes, *, filename: str, content_type: str) -> ParsedDocument:
        for parser in self._parsers:
            if parser.supports(content_type, filename):
                return parser.parse(content, filename=filename, content_type=content_type)
        raise InvalidInputError(f"no parser supports content type {content_type!r}")


def build_default_parser(*, ocr: bool = False) -> DocumentParser:
    """Docling for PDFs, built-in text parser for txt/markdown.

    ``ocr`` is off by default — see :class:`DoclingParser`.
    """
    return CompositeParser((DoclingParser(ocr=ocr), PlainTextParser()))
