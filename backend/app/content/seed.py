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


CLASS_CODES = ("warrior", "rogue", "ranger", "mage", "monk", "cleric", "paladin", "druid", "bard", "shaman")
STAGE_LEVELS = {"promotion": 100, "specialization": 300, "awakening": 600, "capstone": 850, "mastery": 1000}


async def _texts(session: AsyncSession, prefix: str, l10n: dict[str, dict[str, str]], namespace: str) -> None:
    for field, values in l10n.items():
        await l10n_service_seed(session, f"{prefix}.{field}", values, namespace)


async def l10n_service_seed(session: AsyncSession, key: str, values: dict[str, str], namespace: str) -> None:
    await l10n.seed_values(session, key, values, namespace=namespace)


async def seed_classes(session: AsyncSession) -> int:
    from sqlalchemy.dialects.postgresql import insert

    from app.models.classes import ClassProgressionRequirement
    from app.services.content.seeding import ensure_published
    from app.services.content.types import classes as ct

    created = 0
    ref = load_yaml("classes/reference.yaml")
    for code, r in ref["resources"].items():
        await l10n_service_seed(session, f"resource.{code}.name", r["l10n"], "resource")
        created += await ensure_published(
            session,
            ct.RESOURCE_TYPE,
            code,
            {
                "max_value": r["max"],
                "start_value": r["start"],
                "regen_per_s": r["regen_per_s"],
                "decay_per_s": r["decay_per_s"],
            },
        )
    for code, w in ref["weapon_families"].items():
        await l10n_service_seed(session, f"weapon_family.{code}.name", w["l10n"], "weapon_family")
        created += await ensure_published(
            session, ct.WEAPON_FAMILY_TYPE, code, {"hands": w["hands"], "kind": w["kind"]}
        )
    for code, a in ref["armor_families"].items():
        await l10n_service_seed(session, f"armor_family.{code}.name", a["l10n"], "armor_family")
        created += await ensure_published(session, ct.ARMOR_FAMILY_TYPE, code, {})
    for class_code in CLASS_CODES:
        c = load_yaml(f"classes/{class_code}.yaml")
        await _texts(session, f"class.{class_code}", c["l10n"], "class")
        bp = c["base_passive"]
        await _texts(session, f"passive.{bp['code']}", bp["l10n"], "passive")
        created += await ensure_published(
            session,
            ct.BASE_CLASS_TYPE,
            class_code,
            {
                "category": c["category"],
                "sort_order": c["sort_order"],
                "role_key": f"class.{class_code}.role",
                "primary_stat": c["stat_weights"]["primary"],
                "secondary_stat": c["stat_weights"]["secondary"],
                "utility_stat": c["stat_weights"]["utility"],
                "main_damage_stat": c["main_damage_stat"],
                "resources": c["resources"],
                "weapon_families": c["weapons"],
                "armor_families": c["armor"],
                "dual_wield": c["dual_wield"],
                "item_tags": c["item_tags"],
                "base_passive_code": bp["code"],
                "base_effects": bp["effects"],
                "solo_accord": c.get("solo_accord"),
            },
        )
        for bi, b in enumerate(c["branches"]):
            await _texts(session, f"branch.{b['code']}", b["l10n"], "branch")
            await _texts(session, f"passive.{b['passive']['code']}", b["passive"]["l10n"], "passive")
            created += await ensure_published(
                session,
                ct.BRANCH_TYPE,
                b["code"],
                {
                    "base_class_code": class_code,
                    "sort_order": bi,
                    "role_key": f"branch.{b['code']}.role",
                    "passive_code": b["passive"]["code"],
                    "effects": b["passive"]["effects"],
                },
            )
            for si, sp in enumerate(b["specializations"]):
                await _texts(session, f"spec.{sp['code']}", sp["l10n"], "spec")
                await _texts(session, f"passive.{sp['passive']['code']}", sp["passive"]["l10n"], "passive")
                created += await ensure_published(
                    session,
                    ct.SPECIALIZATION_TYPE,
                    sp["code"],
                    {
                        "branch_code": b["code"],
                        "sort_order": si,
                        "role_key": f"spec.{sp['code']}.role",
                        "mastery_noun_key": f"spec.{sp['code']}.mastery_noun",
                        "passive_code": sp["passive"]["code"],
                        "effects": sp["passive"]["effects"],
                    },
                )
    for stage, level in STAGE_LEVELS.items():
        await session.execute(
            insert(ClassProgressionRequirement).values(stage=stage, min_level=level).on_conflict_do_nothing()
        )
    return created


STEPS: list[tuple[str, SeedStep]] = [
    ("rbac", seed_rbac),
    ("localization", seed_localization_files),
    ("balance", seed_balance),
    ("races", seed_races),
    ("classes", seed_classes),
]


async def run_all(session: AsyncSession) -> dict[str, int]:
    results: dict[str, int] = {}
    for name, step in STEPS:
        results[name] = await step(session)
        await session.flush()
        log.info("seed_step", extra={"step": name, "written": results[name]})
    await session.commit()
    return results
