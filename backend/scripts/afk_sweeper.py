"""Resolve finished AFK sessions ahead of claim and expire market listings (cron/compose).

Once: python -m scripts.afk_sweeper [--loop N]."""

import argparse
import asyncio

import app.services.plugins  # noqa: F401
from app.db.session import dispose_engine, get_sessionmaker
from app.services import afk, economy


async def main(loop_s: int) -> None:
    while True:
        async with get_sessionmaker()() as db:
            n = await afk.sweep(db)
            expired = await economy.expire_due(db)
            await db.commit()
        print(f"resolved {n}, expired listings {expired}")
        if not loop_s:
            break
        await asyncio.sleep(loop_s)
    await dispose_engine()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--loop", type=int, default=0, help="seconds between sweeps (0 = run once)")
    asyncio.run(main(ap.parse_args().loop))
