"""Drop and recreate a *development/test* database. Refuses to run when MMO_ENV=prod."""

import argparse
import asyncio
import os
import sys

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine


async def main(url: str) -> None:
    if os.environ.get("MMO_ENV") == "prod":
        sys.exit("refusing to reset a production database")
    target = make_url(url)
    db = target.database
    if not db or not (db.endswith("_test") or db.endswith("_e2e") or db == "mmo"):
        sys.exit(f"refusing to reset unexpected database name: {db}")
    admin = create_async_engine(target.set(database="postgres"), isolation_level="AUTOCOMMIT")
    async with admin.connect() as conn:
        await conn.execute(text(f'DROP DATABASE IF EXISTS "{db}" WITH (FORCE)'))
        await conn.execute(text(f'CREATE DATABASE "{db}"'))
    await admin.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    asyncio.run(main(parser.parse_args().url))
