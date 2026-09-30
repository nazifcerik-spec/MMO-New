"""Idempotent canonical seed runner. Each step is safe to re-run; stable codes never change."""

import logging
from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.content.loader import iter_yaml
from app.localization import service as l10n
from app.services.rbac import seed_rbac

log = logging.getLogger("app.seed")

SeedStep = Callable[[AsyncSession], Awaitable[int]]


async def seed_localization_files(session: AsyncSession) -> int:
    written = 0
    for _, doc in iter_yaml("localization"):
        ns = doc["namespace"]
        for key, values in doc["entries"].items():
            written += await l10n.seed_values(session, key, values, namespace=ns)
    return written


async def seed_balance(session: AsyncSession) -> int:
    from app.services.content.seeding import ensure_published
    from app.services.content.types.balance import BALANCE_TYPE

    created = 0
    for _, doc in iter_yaml("balance"):
        created += await ensure_published(session, BALANCE_TYPE, doc["code"], {"data": doc["data"]})
    return created


STEPS: list[tuple[str, SeedStep]] = [
    ("rbac", seed_rbac),
    ("localization", seed_localization_files),
    ("balance", seed_balance),
]


async def run_all(session: AsyncSession) -> dict[str, int]:
    results: dict[str, int] = {}
    for name, step in STEPS:
        results[name] = await step(session)
        await session.flush()
        log.info("seed_step", extra={"step": name, "written": results[name]})
    await session.commit()
    return results
