"""End-to-end ingestion against the real database: real PlainTextParser, real
structure-aware chunker, real repositories — only the embedder is fake.

Verifies the whole worker path: blob -> parse -> chunk -> embed -> atomic
replace -> READY with chunk_count, including the generated ``tsv`` column that
feeds lexical search, and the FAILED path when parsing blows up.
"""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy import text

from app.modules.documents.application.use_cases import IngestDocument
from app.modules.documents.domain.entities import Document, DocumentStatus
from app.modules.documents.domain.parser import ParsedDocument
from app.modules.documents.infrastructure.parsers import PlainTextParser
from app.modules.documents.infrastructure.repositories import (
    PostgresBlobStore,
    PostgresChunkRepository,
    PostgresDocumentRepository,
)
from tests.integration.support import (
    SequenceEmbedder,
    SessionFactory,
    make_document,
    simple_token_counter,
)

_MARKDOWN = b"""\
# Employee Handbook

## Security

Passwords must be rotated every ninety days without exception.
MFA is mandatory for every staff account.

## Vacations

Employees receive twenty five vacation days each calendar year.
Unused vacation days expire in March.
"""


class ExplodingParser:
    """DocumentParser that always fails, to drive the FAILED path."""

    def supports(self, content_type: str, filename: str) -> bool:
        return True

    def parse(self, content: bytes, *, filename: str, content_type: str) -> ParsedDocument:
        raise RuntimeError("parser exploded on purpose")


def _ingest_use_case(
    session_factory: SessionFactory,
    *,
    parser: PlainTextParser | ExplodingParser,
    embedder: SequenceEmbedder,
    embed_batch_size: int = 2,
) -> IngestDocument:
    return IngestDocument(
        documents=PostgresDocumentRepository(session_factory),
        chunks=PostgresChunkRepository(session_factory),
        blobs=PostgresBlobStore(session_factory),
        parser=parser,
        embedder=embedder,
        count_tokens=simple_token_counter,
        chunk_max_tokens=24,
        chunk_overlap_tokens=4,
        embed_batch_size=embed_batch_size,
    )


async def _seed_upload(session_factory: SessionFactory, content: bytes) -> Document:
    document = make_document(
        filename="handbook.md", status=DocumentStatus.QUEUED, size_bytes=len(content)
    )
    await PostgresDocumentRepository(session_factory).add(document)
    await PostgresBlobStore(session_factory).put(document.id, content)
    return document


async def test_markdown_upload_reaches_ready_with_searchable_chunks(
    session_factory: SessionFactory,
) -> None:
    document = await _seed_upload(session_factory, _MARKDOWN)
    embedder = SequenceEmbedder()
    ingest = _ingest_use_case(session_factory, parser=PlainTextParser(), embedder=embedder)

    await ingest(document.id)

    ready = await PostgresDocumentRepository(session_factory).get(document.id)
    assert ready is not None
    assert ready.status is DocumentStatus.READY
    assert ready.error is None
    assert ready.chunk_count >= 2  # two heading sections at minimum

    async with session_factory() as session:
        rows = (
            (
                await session.execute(
                    text(
                        "SELECT seq, heading_path, tsv IS NOT NULL AS has_tsv,"
                        " vector_dims(embedding) AS dims"
                        " FROM chunks WHERE document_id = :doc ORDER BY seq"
                    ),
                    {"doc": document.id},
                )
            )
            .mappings()
            .all()
        )
        matched = (
            await session.execute(
                text(
                    "SELECT count(*) FROM chunks WHERE document_id = :doc"
                    " AND tsv @@ websearch_to_tsquery('english', 'vacation days')"
                ),
                {"doc": document.id},
            )
        ).scalar_one()

    assert len(rows) == ready.chunk_count
    assert [row["seq"] for row in rows] == list(range(len(rows)))
    # The generated tsv column is populated and actually searchable.
    assert all(row["has_tsv"] for row in rows)
    assert int(matched) >= 1
    assert all(row["dims"] == 1536 for row in rows)
    # Markdown headings became heading_path context on the chunks.
    paths = {tuple(row["heading_path"]) for row in rows}
    assert ("Employee Handbook", "Security") in paths
    assert ("Employee Handbook", "Vacations") in paths
    # Batching honoured the configured size.
    assert all(size <= 2 for size in embedder.batch_sizes)
    assert sum(embedder.batch_sizes) == len(rows)


async def test_reingest_replaces_chunks_instead_of_appending(
    session_factory: SessionFactory,
) -> None:
    document = await _seed_upload(session_factory, _MARKDOWN)
    ingest = _ingest_use_case(
        session_factory, parser=PlainTextParser(), embedder=SequenceEmbedder()
    )

    await ingest(document.id)
    await ingest(document.id)

    ready = await PostgresDocumentRepository(session_factory).get(document.id)
    assert ready is not None
    assert ready.status is DocumentStatus.READY
    async with session_factory() as session:
        count = (
            await session.execute(
                text("SELECT count(*) FROM chunks WHERE document_id = :doc"),
                {"doc": document.id},
            )
        ).scalar_one()
    assert int(count) == ready.chunk_count


async def test_parser_failure_marks_document_failed_with_reason(
    session_factory: SessionFactory,
) -> None:
    document = await _seed_upload(session_factory, _MARKDOWN)
    ingest = _ingest_use_case(
        session_factory, parser=ExplodingParser(), embedder=SequenceEmbedder()
    )

    await ingest(document.id)  # the use case swallows the failure by contract

    failed = await PostgresDocumentRepository(session_factory).get(document.id)
    assert failed is not None
    assert failed.status is DocumentStatus.FAILED
    assert failed.error is not None
    assert "parser exploded on purpose" in failed.error
    async with session_factory() as session:
        count = (
            await session.execute(
                text("SELECT count(*) FROM chunks WHERE document_id = :doc"),
                {"doc": document.id},
            )
        ).scalar_one()
    assert int(count) == 0


async def test_empty_document_fails_with_no_chunks_error(
    session_factory: SessionFactory,
) -> None:
    document = await _seed_upload(session_factory, b"\n\n   \n")
    ingest = _ingest_use_case(
        session_factory, parser=PlainTextParser(), embedder=SequenceEmbedder()
    )

    await ingest(document.id)

    failed = await PostgresDocumentRepository(session_factory).get(document.id)
    assert failed is not None
    assert failed.status is DocumentStatus.FAILED
    assert failed.error is not None
    assert "no chunks" in failed.error


async def test_unknown_document_is_a_noop(session_factory: SessionFactory) -> None:
    ingest = _ingest_use_case(
        session_factory, parser=PlainTextParser(), embedder=SequenceEmbedder()
    )
    await ingest(uuid4())  # must neither raise nor create rows
    async with session_factory() as session:
        count = (await session.execute(text("SELECT count(*) FROM documents"))).scalar_one()
    assert int(count) == 0
