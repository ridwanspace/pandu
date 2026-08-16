"""arq worker entrypoint: ``uv run arq app.worker.WorkerSettings``.

This is the worker-side composition root: it wires the ingest pipeline once
at startup and keeps the job function itself thin.
"""

from __future__ import annotations

from typing import Any, ClassVar
from uuid import UUID

import structlog
from arq.connections import RedisSettings

from app.config import get_settings
from app.modules.documents.application.use_cases import IngestDocument
from app.modules.documents.infrastructure.job_queue import INGEST_TASK_NAME
from app.modules.documents.infrastructure.parsers import build_default_parser
from app.modules.documents.infrastructure.repositories import (
    PostgresBlobStore,
    PostgresChunkRepository,
    PostgresDocumentRepository,
)
from app.modules.documents.infrastructure.token_counter import build_token_counter
from app.shared.infrastructure.ai.cost_store import PostgresCostRecorder
from app.shared.infrastructure.ai.factory import ProviderFactory
from app.shared.infrastructure.ai.metering import MeteredEmbeddingProvider
from app.shared.infrastructure.ai.pricing import PriceTable
from app.shared.infrastructure.db.engine import build_engine, build_session_factory

logger = structlog.get_logger(__name__)


async def startup(ctx: dict[Any, Any]) -> None:
    settings = get_settings()
    engine = build_engine(settings.database_url)
    session_factory = build_session_factory(engine)
    # Ingestion embeddings are metered too — bulk indexing dominates token
    # spend, so leaving it out would make the cost dashboard a lie.
    embedder = MeteredEmbeddingProvider(
        ProviderFactory(settings).build_embeddings(settings.ai_embed_model),
        prices=PriceTable(),
        recorder=PostgresCostRecorder(session_factory),
    )
    ctx["engine"] = engine
    ctx["ingest_document"] = IngestDocument(
        documents=PostgresDocumentRepository(session_factory),
        chunks=PostgresChunkRepository(session_factory),
        blobs=PostgresBlobStore(session_factory),
        parser=build_default_parser(),
        embedder=embedder,
        count_tokens=build_token_counter(),
        chunk_max_tokens=settings.chunk_max_tokens,
        chunk_overlap_tokens=settings.chunk_overlap_tokens,
        embed_batch_size=settings.embed_batch_size,
    )
    logger.info("worker_started")


async def shutdown(ctx: dict[Any, Any]) -> None:
    await ctx["engine"].dispose()
    logger.info("worker_stopped")


async def ingest_document(ctx: dict[Any, Any], document_id: str) -> None:
    use_case: IngestDocument = ctx["ingest_document"]
    await use_case(UUID(document_id))


if ingest_document.__name__ != INGEST_TASK_NAME:  # queue and worker must agree
    msg = "worker task name drifted from ArqIngestJobQueue task name"
    raise RuntimeError(msg)


class WorkerSettings:
    """arq worker configuration (see §3.5 ingestion flow)."""

    functions: ClassVar = [ingest_document]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    max_jobs = 4
    # CPU-parsing a dense 500-page publication (e.g. NIST SP 800-53r5) can
    # take tens of minutes with Docling's layout models; keep headroom.
    job_timeout = 60 * 60
