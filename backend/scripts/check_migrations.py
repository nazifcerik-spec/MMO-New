"""Fail if SQLAlchemy models and the Alembic head schema differ (migration drift)."""

import asyncio
import os
import sys

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy.ext.asyncio import create_async_engine

import app.models  # noqa: F401
from app.db.base import Base

URL = os.environ.get("MMO_DATABASE_URL", "postgresql+asyncpg://mmo:mmo@localhost:5432/mmo_test")


async def main() -> int:
    engine = create_async_engine(URL)
    async with engine.connect() as conn:
        diff = await conn.run_sync(
            lambda sync_conn: compare_metadata(
                MigrationContext.configure(sync_conn, opts={"compare_type": True}), Base.metadata
            )
        )
    await engine.dispose()
    if diff:
        for d in diff:
            print("DRIFT:", d)
        return 1
    print("no migration drift")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
