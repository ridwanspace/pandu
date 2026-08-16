"""Documents module — arq-backed ingest job queue adapter."""

from __future__ import annotations

from uuid import UUID

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

INGEST_TASK_NAME = "ingest_document"


class ArqIngestJobQueue:
    """Enqueues ingest jobs on Redis via arq.

    The pool is created lazily on first use (the event loop is not running at
    construction time in the composition root) and reused afterwards.
    """

    def __init__(self, *, redis_url: str) -> None:
        self._redis_settings = RedisSettings.from_dsn(redis_url)
        self._pool: ArqRedis | None = None

    async def enqueue_ingest(self, document_id: UUID) -> None:
        pool = await self._get_pool()
        await pool.enqueue_job(INGEST_TASK_NAME, str(document_id))

    async def aclose(self) -> None:
        if self._pool is not None:
            await self._pool.aclose()
            self._pool = None

    async def _get_pool(self) -> ArqRedis:
        if self._pool is None:
            self._pool = await create_pool(self._redis_settings)
        return self._pool
