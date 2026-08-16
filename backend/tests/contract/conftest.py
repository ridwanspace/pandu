"""Contract-suite fixtures: the real app (``create_app``) wired to dedicated
postgres + redis testcontainers and served by uvicorn in a background thread.

A live server (rather than an in-process ASGI transport) is deliberate: the
app owns pooled asyncpg/redis connections bound to one event loop, and both
schemathesis and per-test asyncio loops would otherwise hop loops between
requests. One server thread = one loop = realistic pooling, and lifespan runs.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from threading import Thread

import httpx
import pytest
import uvicorn
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool
from testcontainers.community.postgres import PostgresContainer
from testcontainers.community.redis import RedisContainer

import app.modules.chat.infrastructure.models
import app.modules.documents.infrastructure.models
import app.modules.evaluation.infrastructure.models
import app.shared.infrastructure.models  # noqa: F401
from app.bootstrap import create_app
from app.config import get_settings
from app.shared.infrastructure.db.base import Base
from tests.integration.support import PG_IMAGE, run_migrations

API_KEY = "test-key"
_THIS_DIR = Path(__file__).resolve().parent


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Contract tests need docker too; keep `pytest tests/unit` docker-free."""
    for item in items:
        if item.path is not None and item.path.is_relative_to(_THIS_DIR):
            item.add_marker(pytest.mark.integration)


@pytest.fixture(scope="session")
def contract_database_url() -> Iterator[str]:
    with PostgresContainer(PG_IMAGE, driver="asyncpg") as container:
        url = container.get_connection_url()
        run_migrations(url)
        yield url


@pytest.fixture(scope="session")
def contract_redis_url() -> Iterator[str]:
    with RedisContainer("redis:7-alpine") as container:
        host = container.get_container_host_ip()
        port = container.get_exposed_port(6379)
        yield f"redis://{host}:{port}/0"


@pytest.fixture(scope="session")
def api_base_url(contract_database_url: str, contract_redis_url: str) -> Iterator[str]:
    """The composed FastAPI app served over HTTP on an ephemeral port."""
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setenv("DATABASE_URL", contract_database_url)
    monkeypatch.setenv("REDIS_URL", contract_redis_url)
    monkeypatch.setenv("API_KEYS", API_KEY)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")  # never called by these tests
    monkeypatch.setenv("AI_FALLBACK_MODEL", "")
    monkeypatch.setenv("RERANKER", "none")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "")
    # Schemathesis fires hundreds of requests; the default 60/min would 429.
    monkeypatch.setenv("RATE_LIMIT_REQUESTS", "100000")
    get_settings.cache_clear()

    server = uvicorn.Server(
        uvicorn.Config(create_app(), host="127.0.0.1", port=0, log_level="warning")
    )
    thread = Thread(target=server.run, name="uvicorn-contract", daemon=True)
    thread.start()
    deadline = time.monotonic() + 30
    while not server.started:
        if not thread.is_alive() or time.monotonic() > deadline:
            raise RuntimeError("contract API server failed to start")
        time.sleep(0.05)
    port = server.servers[0].sockets[0].getsockname()[1]

    yield f"http://127.0.0.1:{port}"

    server.should_exit = True
    thread.join(timeout=10)
    monkeypatch.undo()
    get_settings.cache_clear()


@pytest.fixture(scope="session")
def client(api_base_url: str) -> Iterator[httpx.Client]:
    with httpx.Client(base_url=api_base_url, headers={"X-API-Key": API_KEY}, timeout=30) as authed:
        yield authed


@pytest.fixture(scope="session")
def anon_client(api_base_url: str) -> Iterator[httpx.Client]:
    with httpx.Client(base_url=api_base_url, timeout=30) as anonymous:
        yield anonymous


@pytest.fixture(scope="session")
def truncate_all(contract_database_url: str) -> Callable[[], None]:
    """Wipe every table; contract tests run sync, so drive asyncpg via run()."""

    async def _go() -> None:
        engine = create_async_engine(contract_database_url, poolclass=NullPool)
        try:
            tables = ", ".join(f'"{table.name}"' for table in Base.metadata.sorted_tables)
            async with engine.begin() as connection:
                await connection.execute(text(f"TRUNCATE TABLE {tables} CASCADE"))
        finally:
            await engine.dispose()

    def _truncate() -> None:
        asyncio.run(_go())

    return _truncate


@pytest.fixture
def clean_db(truncate_all: Callable[[], None]) -> None:
    """Empty database before a test that asserts on exact collection contents."""
    truncate_all()
