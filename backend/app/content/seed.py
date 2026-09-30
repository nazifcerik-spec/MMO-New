"""Idempotent canonical seed runner. Each step is safe to re-run; stable codes never change."""

import logging
from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.content.loader import iter_yaml, load_yaml
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


async def seed_races(session: AsyncSession) -> int:
    from app.services.content.seeding import ensure_published
    from app.services.content.types.race import RACE_TYPE

    created = 0
    for race in load_yaml("races/races.yaml")["races"]:
        code = race["code"]
        for field, values in race["l10n"].items():
            await l10n.seed_values(session, f"race.{code}.{field}", values, namespace="race")
        data = {
            "sort_order": race["sort_order"],
            "identity": race["identity"],
            "trait_name_key": f"race.{code}.trait_name",
            "trait_description_key": f"race.{code}.trait_description",
            "title_key": f"race.{code}.title",
            "affinity": race["affinity"],
            "effects": race["effects"],
        }
        created += await ensure_published(session, RACE_TYPE, code, data)
    return created


STEPS: list[tuple[str, SeedStep]] = [
    ("rbac", seed_rbac),
    ("localization", seed_localization_files),
    ("balance", seed_balance),
    ("races", seed_races),
]


async def run_all(session: AsyncSession) -> dict[str, int]:
    results: dict[str, int] = {}
    for name, step in STEPS:
        results[name] = await step(session)
        await session.flush()
        log.info("seed_step", extra={"step": name, "written": results[name]})
    await session.commit()
    return results
