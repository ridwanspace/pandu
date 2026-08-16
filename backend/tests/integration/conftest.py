"""Integration fixtures: one pgvector container per session, real migrations,
a fresh engine per test (pytest-asyncio uses a function-scoped event loop, and
asyncpg connections are bound to the loop that created them), and truncation
between tests so state never leaks.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from testcontainers.community.postgres import PostgresContainer

# Import every model module so Base.metadata covers all tables (for TRUNCATE).
import app.modules.chat.infrastructure.models
import app.modules.documents.infrastructure.models
import app.modules.evaluation.infrastructure.models
import app.shared.infrastructure.models  # noqa: F401
from app.shared.infrastructure.db.base import Base
from app.shared.infrastructure.db.engine import build_engine, build_session_factory
from tests.integration.support import PG_IMAGE, run_migrations

_THIS_DIR = Path(__file__).resolve().parent


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Every test in this directory requires docker."""
    for item in items:
        if item.path is not None and item.path.is_relative_to(_THIS_DIR):
            item.add_marker(pytest.mark.integration)


@pytest.fixture(scope="session")
def pg_container() -> Iterator[PostgresContainer]:
    with PostgresContainer(PG_IMAGE, driver="asyncpg") as container:
        yield container


@pytest.fixture(scope="session")
def database_url(pg_container: PostgresContainer) -> str:
    """Async DSN for the container, with the real Alembic migrations applied."""
    url = pg_container.get_connection_url()
    run_migrations(url)
    return url


@pytest.fixture
async def session_factory(
    database_url: str,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Session factory over a per-test engine; truncates all tables afterwards."""
    engine = build_engine(database_url)
    try:
        yield build_session_factory(engine)
        tables = ", ".join(f'"{table.name}"' for table in Base.metadata.sorted_tables)
        async with engine.begin() as connection:
            await connection.execute(text(f"TRUNCATE TABLE {tables} CASCADE"))
    finally:
        await engine.dispose()
