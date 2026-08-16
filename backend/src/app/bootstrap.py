"""Composition root — the ONE place adapters are instantiated and wired.

Everything below the API layer depends on ports; this module chooses the
concrete adapters from env config and assembles the FastAPI application.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI
from redis.asyncio import Redis

from app.config import Settings, get_settings
from app.modules.chat.application.use_cases import (
    AskQuestion,
    GetMessages,
    ListConversations,
    StartConversation,
)
from app.modules.chat.infrastructure.repositories import (
    PostgresConversationRepository,
    PostgresMessageRepository,
)
from app.modules.chat.presentation.controllers import build_router as build_chat_router
from app.modules.documents.application.use_cases import (
    DeleteDocument,
    GetDocument,
    ListDocuments,
    PreviewChunks,
    UploadDocument,
)
from app.modules.documents.infrastructure.job_queue import ArqIngestJobQueue
from app.modules.documents.infrastructure.repositories import (
    PostgresBlobStore,
    PostgresChunkRepository,
    PostgresDocumentRepository,
)
from app.modules.documents.presentation.controllers import (
    build_router as build_documents_router,
)
from app.modules.evaluation.application.use_cases import ListEvalRuns, RunRetrievalEval
from app.modules.evaluation.infrastructure.dataset_files import golden_dataset_loader
from app.modules.evaluation.infrastructure.repositories import PostgresEvalRunRepository
from app.modules.evaluation.presentation.controllers import (
    build_router as build_evals_router,
)
from app.modules.retrieval.application.use_cases import RetrieveContext
from app.modules.retrieval.infrastructure.pg_search_index import PostgresSearchIndex
from app.modules.retrieval.presentation.controllers import (
    build_router as build_retrieval_router,
)
from app.shared.domain.ports.llm import LLMProvider
from app.shared.domain.ports.tracing import Tracer
from app.shared.domain.values import ModelRef
from app.shared.infrastructure.ai.cost_store import CostStatsReader, PostgresCostRecorder
from app.shared.infrastructure.ai.factory import ProviderFactory
from app.shared.infrastructure.ai.fallback import FallbackLLMProvider
from app.shared.infrastructure.ai.metering import (
    MeteredEmbeddingProvider,
    MeteredLLMProvider,
    MeteredReranker,
)
from app.shared.infrastructure.ai.pricing import PriceTable
from app.shared.infrastructure.ai.tracing import LangfuseTracer, NoopTracer
from app.shared.infrastructure.db.engine import build_engine, build_session_factory
from app.shared.infrastructure.logging import configure_logging
from app.shared.infrastructure.rate_limit import (
    RedisRateLimiter,
    build_rate_limit_dependency,
)
from app.shared.presentation.auth import require_api_key
from app.shared.presentation.costs import get_cost_stats_reader
from app.shared.presentation.costs import router as costs_router
from app.shared.presentation.security_headers import SecurityHeadersMiddleware

GOLDEN_DATASET = Path(__file__).resolve().parents[2] / "evals" / "golden" / "golden_v1.jsonl"


def _build_tracer(settings: Settings) -> Tracer:
    if settings.langfuse_public_key and settings.langfuse_secret_key:
        return LangfuseTracer(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_host,
        )
    return NoopTracer()


def _build_llm(
    settings: Settings,
    factory: ProviderFactory,
    prices: PriceTable,
    recorder: PostgresCostRecorder,
) -> LLMProvider:
    chain: list[tuple[ModelRef, LLMProvider]] = [
        (ModelRef.parse(settings.ai_chat_model), factory.build_llm(settings.ai_chat_model))
    ]
    if settings.ai_fallback_model:
        chain.append(
            (
                ModelRef.parse(settings.ai_fallback_model),
                factory.build_llm(settings.ai_fallback_model),
            )
        )
    return MeteredLLMProvider(FallbackLLMProvider(chain), prices=prices, recorder=recorder)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, json_output=settings.environment != "dev")

    # ── Infrastructure ───────────────────────────────────────────────────
    engine = build_engine(settings.database_url)
    session_factory = build_session_factory(engine)
    redis = Redis.from_url(settings.redis_url)

    # ── Shared AI seam: factory → fallback → metering ────────────────────
    factory = ProviderFactory(settings)
    prices = PriceTable()
    recorder = PostgresCostRecorder(session_factory)
    tracer = _build_tracer(settings)
    llm = _build_llm(settings, factory, prices, recorder)
    embedder = MeteredEmbeddingProvider(
        factory.build_embeddings(settings.ai_embed_model), prices=prices, recorder=recorder
    )
    reranker = MeteredReranker(factory.build_reranker(settings.reranker), recorder=recorder)

    # ── Repositories ─────────────────────────────────────────────────────
    documents = PostgresDocumentRepository(session_factory)
    chunks = PostgresChunkRepository(session_factory)
    blobs = PostgresBlobStore(session_factory)
    conversations = PostgresConversationRepository(session_factory)
    messages = PostgresMessageRepository(session_factory)
    eval_runs = PostgresEvalRunRepository(session_factory)

    # ── Use cases ────────────────────────────────────────────────────────
    retrieve = RetrieveContext(
        embedder=embedder,
        index=PostgresSearchIndex(session_factory),
        reranker=reranker,
        tracer=tracer,
        candidates=settings.retrieval_candidates,
        top_k=settings.retrieval_top_k,
        rrf_k=settings.rrf_k,
    )
    ask = AskQuestion(
        conversations=conversations,
        messages=messages,
        retrieve=retrieve,
        llm=llm,
        tracer=tracer,
        estimate_cost=prices.cost_for,
        max_question_chars=settings.max_question_chars,
    )
    run_retrieval_eval = RunRetrievalEval(
        retrieve=retrieve,
        runs=eval_runs,
        dataset_loader=golden_dataset_loader(GOLDEN_DATASET),
        k=settings.retrieval_top_k,
        dataset_version="golden_v1",
        config={
            "embed_model": settings.ai_embed_model,
            "reranker": settings.reranker,
            "rrf_k": str(settings.rrf_k),
            "candidates": str(settings.retrieval_candidates),
        },
    )

    # ── Application ──────────────────────────────────────────────────────
    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        tracer.flush()
        await redis.aclose()
        await engine.dispose()

    app = FastAPI(
        title="Pandu",
        summary="Grounded answers, guided by your documents.",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.add_middleware(SecurityHeadersMiddleware)

    limiter = RedisRateLimiter(
        redis,
        limit=settings.rate_limit_requests,
        window_seconds=settings.rate_limit_window_seconds,
    )
    api = APIRouter(
        prefix="/api/v1",
        dependencies=[
            Depends(require_api_key),
            Depends(build_rate_limit_dependency(limiter)),
        ],
    )
    api.include_router(
        build_documents_router(
            upload_document=UploadDocument(
                documents=documents,
                blobs=blobs,
                jobs=ArqIngestJobQueue(redis_url=settings.redis_url),
                max_upload_bytes=settings.max_upload_bytes,
                chunk_max_tokens=settings.chunk_max_tokens,
                chunk_overlap_tokens=settings.chunk_overlap_tokens,
            ),
            list_documents=ListDocuments(documents=documents),
            get_document=GetDocument(documents=documents),
            delete_document=DeleteDocument(documents=documents, blobs=blobs),
            preview_chunks=PreviewChunks(documents=documents, chunks=chunks),
        )
    )
    api.include_router(build_retrieval_router(retrieve))
    api.include_router(
        build_chat_router(
            start=StartConversation(conversations=conversations),
            list_conversations=ListConversations(conversations=conversations),
            get_messages=GetMessages(conversations=conversations, messages=messages),
            ask=ask,
        )
    )
    api.include_router(
        build_evals_router(
            list_runs=ListEvalRuns(runs=eval_runs),
            run_retrieval=run_retrieval_eval,
        )
    )
    api.include_router(costs_router)
    app.include_router(api)
    app.dependency_overrides[get_cost_stats_reader] = lambda: CostStatsReader(session_factory)

    @app.get("/health", tags=["health"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
