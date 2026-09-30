"""CLI: apply canonical seeds to the configured database (idempotent)."""

import asyncio
import json

from app.content.seed import run_all
from app.db.session import dispose_engine, get_sessionmaker


async def main() -> None:
    async with get_sessionmaker()() as session:
        results = await run_all(session)
    await dispose_engine()
    print(json.dumps(results))


if __name__ == "__main__":
    asyncio.run(main())
