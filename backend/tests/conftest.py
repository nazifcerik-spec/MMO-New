import os

os.environ.setdefault("MMO_ENV", "test")
os.environ.setdefault("MMO_DATABASE_URL", "postgresql+asyncpg://mmo:mmo@localhost:5432/mmo_test")
os.environ.setdefault("MMO_REDIS_URL", "redis://localhost:6379/15")
os.environ.setdefault("MMO_LOG_JSON", "false")
os.environ.setdefault("MMO_LOG_LEVEL", "WARNING")

from collections.abc import AsyncIterator

import pytest
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.config import get_settings
from app.main import create_app

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


async def _reset_database() -> None:
    engine = create_async_engine(get_settings().database_url)
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
    await engine.dispose()


def _upgrade_head() -> None:
    cfg = Config(os.path.join(BACKEND_DIR, "alembic.ini"))
    cfg.attributes["configure_logger"] = False
    cfg.set_main_option("sqlalchemy.url", get_settings().database_url)
    command.upgrade(cfg, "head")


@pytest.fixture(scope="session", autouse=True)
async def migrated_db() -> AsyncIterator[None]:
    await _reset_database()
    import asyncio

    await asyncio.to_thread(_upgrade_head)
    from app.content.seed import run_all
    from app.db.session import dispose_engine, get_sessionmaker

    async with get_sessionmaker()() as session:
        await run_all(session)
    await dispose_engine()
    yield


@pytest.fixture(scope="session")
async def app():  # type: ignore[no-untyped-def]
    application = create_app()
    yield application


@pytest.fixture
async def client(app) -> AsyncIterator[AsyncClient]:  # type: ignore[no-untyped-def]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture
async def db() -> AsyncIterator[AsyncSession]:
    """A session whose work is rolled back after the test."""
    from app.db.session import get_sessionmaker

    async with get_sessionmaker()() as session:
        yield session
        await session.rollback()
