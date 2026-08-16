"""Embedding-model migration CLI: ``python -m app.reindex [--document-id ID]``.

Re-embeds stored chunk text with the embedding model currently configured in
``AI_EMBED_MODEL`` — no re-parsing. Run it once right after changing the env
var so chunk vectors and query vectors stay in the same space.
"""

from __future__ import annotations

import argparse
import asyncio
from uuid import UUID

from app.config import get_settings
from app.modules.documents.application.use_cases import ReembedDocuments
from app.modules.documents.infrastructure.repositories import (
    PostgresChunkRepository,
    PostgresDocumentRepository,
)
from app.shared.infrastructure.ai.cost_store import PostgresCostRecorder
from app.shared.infrastructure.ai.factory import ProviderFactory
from app.shared.infrastructure.ai.metering import MeteredEmbeddingProvider
from app.shared.infrastructure.ai.pricing import PriceTable
from app.shared.infrastructure.db.engine import build_engine, build_session_factory
from app.shared.infrastructure.logging import configure_logging


async def _run(document_id: UUID | None) -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    engine = build_engine(settings.database_url)
    try:
        session_factory = build_session_factory(engine)
        embedder = MeteredEmbeddingProvider(
            ProviderFactory(settings).build_embeddings(settings.ai_embed_model),
            prices=PriceTable(),
            recorder=PostgresCostRecorder(session_factory),
        )
        reembed = ReembedDocuments(
            documents=PostgresDocumentRepository(session_factory),
            chunks=PostgresChunkRepository(session_factory),
            embedder=embedder,
            embed_batch_size=settings.embed_batch_size,
        )
        report = await reembed(document_id)
        print(
            f"re-embedded {report.chunks} chunks across {report.documents} document(s) "
            f"with {report.model or settings.ai_embed_model} ({report.skipped} skipped)"
        )
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--document-id", type=UUID, default=None)
    args = parser.parse_args()
    asyncio.run(_run(args.document_id))


if __name__ == "__main__":
    main()
