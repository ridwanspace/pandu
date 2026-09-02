"""Ingest the seed corpus directly, without the API or the job queue.

The eval suite scores the *live* retrieval pipeline, so the corpus has to be
in Postgres before any run — but spinning up the API, Redis and an arq worker
just to load four fixed PDFs adds three moving parts that can fail for reasons
unrelated to retrieval quality. This script drives the same two use cases the
worker drives (``UploadDocument`` then ``IngestDocument``), synchronously, so
CI and a laptop follow the identical path.

Run from ``backend/``::

    uv run python -m evals.ingest_corpus            # skips already-ingested files
    uv run python -m evals.ingest_corpus --force    # re-ingest everything

Idempotent by filename: a document already present and ``ready`` is left
alone, so re-running before an eval is cheap and safe.
"""

from __future__ import annotations

import argparse
import asyncio
import mimetypes
from pathlib import Path
from uuid import UUID

from app.config import get_settings
from app.modules.documents.application.use_cases import IngestDocument, UploadDocument
from app.modules.documents.infrastructure.parsers import build_default_parser
from app.modules.documents.infrastructure.repositories import (
    PostgresBlobStore,
    PostgresChunkRepository,
    PostgresDocumentRepository,
)
from app.modules.documents.infrastructure.token_counter import build_token_counter
from app.shared.infrastructure.ai.factory import ProviderFactory
from app.shared.infrastructure.db.engine import build_engine, build_session_factory

CORPUS_DIR = Path(__file__).resolve().parent / "corpus"


class _NullJobQueue:
    """Satisfies the IngestJobQueue port; ingestion runs inline below instead."""

    async def enqueue_ingest(self, document_id: UUID) -> None:
        return None


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m evals.ingest_corpus",
        description="Load the seed corpus into Postgres for eval runs.",
    )
    parser.add_argument(
        "--force", action="store_true", help="re-ingest documents that are already present"
    )
    parser.add_argument(
        "--corpus-dir", type=Path, default=CORPUS_DIR, help=f"default: {CORPUS_DIR}"
    )
    return parser.parse_args(argv)


async def _amain(args: argparse.Namespace) -> int:
    settings = get_settings()
    files = sorted(args.corpus_dir.glob("*.pdf")) + sorted(args.corpus_dir.glob("*.txt"))
    if not files:
        print(f"No corpus files in {args.corpus_dir} — run scripts/fetch_corpus.sh first.")
        return 1

    engine = build_engine(settings.database_url)
    try:
        session_factory = build_session_factory(engine)
        factory = ProviderFactory(settings)
        documents = PostgresDocumentRepository(session_factory)
        chunks = PostgresChunkRepository(session_factory)
        blobs = PostgresBlobStore(session_factory)

        upload = UploadDocument(
            documents=documents,
            blobs=blobs,
            jobs=_NullJobQueue(),
            max_upload_bytes=max(settings.max_upload_bytes, 64 * 1024 * 1024),
            chunk_max_tokens=settings.chunk_max_tokens,
            chunk_overlap_tokens=settings.chunk_overlap_tokens,
        )
        ingest = IngestDocument(
            documents=documents,
            chunks=chunks,
            blobs=blobs,
            parser=build_default_parser(ocr=settings.docling_ocr),
            embedder=factory.build_embeddings(settings.ai_embed_model),
            count_tokens=build_token_counter(),
            chunk_max_tokens=settings.chunk_max_tokens,
            chunk_overlap_tokens=settings.chunk_overlap_tokens,
            embed_batch_size=settings.embed_batch_size,
        )

        existing = {doc.filename: doc for doc in await documents.list_all()}
        print(f"Corpus: {len(files)} file(s) in {args.corpus_dir}")
        print(f"Embeddings: {settings.ai_embed_model}\n")

        for path in files:
            present = existing.get(path.name)
            if present is not None and present.status.value == "ready" and not args.force:
                print(f"  = {path.name:<28} already ready, skipping")
                continue
            content_type = mimetypes.guess_type(path.name)[0] or "application/pdf"
            document = await upload(
                filename=path.name, content_type=content_type, content=path.read_bytes()
            )
            print(f"  + {path.name:<28} uploaded ({path.stat().st_size // 1024} KiB), ingesting...")
            await ingest(document.id)
            refreshed = await documents.get(document.id)
            status = refreshed.status.value if refreshed is not None else "unknown"
            count = refreshed.chunk_count if refreshed is not None else 0
            print(f"    -> {status}, {count} chunks")

        ready = [doc for doc in await documents.list_all() if doc.status.value == "ready"]
        total = sum(doc.chunk_count for doc in ready)
        print(f"\n{len(ready)} document(s) ready, {total} chunks indexed.")
    finally:
        await engine.dispose()
    return 0


def main(argv: list[str] | None = None) -> None:
    raise SystemExit(asyncio.run(_amain(_parse_args(argv))))


if __name__ == "__main__":
    main()
