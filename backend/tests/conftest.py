import os

os.environ.setdefault("MMO_ENV", "test")
os.environ.setdefault("MMO_DATABASE_URL", "postgresql+asyncpg://mmo:mmo@localhost:5432/mmo_test")
os.environ.setdefault("MMO_REDIS_URL", "redis://localhost:6379/15")
os.environ.setdefault("MMO_LOG_JSON", "false")
os.environ.setdefault("MMO_LOG_LEVEL", "WARNING")
os.environ.setdefault("MMO_RL_REGISTER_IP", "100000/3600")
os.environ.setdefault("MMO_RL_LOGIN_IP", "100000/60")

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


@pytest.fixture(scope="session", autouse=True)
async def _flush_test_redis() -> AsyncIterator[None]:
    from app.db.redis import close_redis, get_redis

    await get_redis().flushdb()
    yield
    await close_redis()


class UserClient:
    def __init__(self, client: AsyncClient, email: str, password: str, user_id: int) -> None:
        self.http = client
        self.email = email
        self.password = password
        self.user_id = user_id


@pytest.fixture
async def make_client(app):  # type: ignore[no-untyped-def]
    """Factory: new authenticated client (fresh cookie jar) optionally holding extra roles."""
    import uuid

    from app.db.session import get_sessionmaker
    from app.services import rbac

    opened: list[AsyncClient] = []

    async def _make(*roles: str, email: str | None = None, password: str = "correct-horse-battery") -> UserClient:
        c = AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test", headers={"X-Forwarded-For": uuid.uuid4().hex}
        )
        opened.append(c)
        email = email or f"u{uuid.uuid4().hex[:12]}@example.com"
        r = await c.post("/api/v1/auth/register", json={"email": email, "password": password})
        assert r.status_code == 201, r.text
        uid = r.json()["id"]
        if roles:
            async with get_sessionmaker()() as s:
                for role in roles:
                    await rbac.assign_role(s, user_id=uid, role_code=role, actor_id=None, actor_rank=None)
                await s.commit()
        c.headers["X-CSRF-Token"] = c.cookies["csrf_token"]
        return UserClient(c, email, password, uid)

    yield _make
    for c in opened:
        await c.aclose()


@pytest.fixture
async def make_character():  # type: ignore[no-untyped-def]
    """Insert a character directly (bypasses content-dependent creation rules) for engine/service tests."""
    import uuid

    from app.content.names import name_key
    from app.db.session import get_sessionmaker
    from app.models.character import Character, CharacterSettings

    async def _make(user_id: int, *, level: int = 1, unspent: int = 0, race_id: int = 1, base_class_id: int = 1) -> int:
        name = "T" + "".join(chr(97 + (b % 26)) for b in uuid.uuid4().bytes[:10])
        async with get_sessionmaker()() as s:
            ch = Character(
                user_id=user_id,
                name=name,
                name_normalized=name_key(name),
                race_id=race_id,
                base_class_id=base_class_id,
                level=level,
                xp=0,
                unspent_stat_points=unspent,
            )
            s.add(ch)
            await s.flush()
            s.add(CharacterSettings(character_id=ch.id))
            await s.commit()
            return ch.id

    return _make
