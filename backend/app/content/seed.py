"""Idempotent canonical seed runner. Each step is safe to re-run; stable codes never change."""

import logging
from collections.abc import Awaitable, Callable
from typing import Any

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


MASTERY_NAME_PATTERNS = {
    "en": "{name} Mastery",
    "tr": "{name} Ustalığı",
    "zh-CN": "{name}精通",
    "es": "Maestría de {name}",
}


def _trigger_of(effects: list[dict[str, Any]]) -> str | None:
    for e in effects:
        if e["effect_type"] == "PROC_CHANCE":
            return str(e["params"].get("trigger", "on_hit"))
    return None


async def seed_skills(session: AsyncSession) -> int:
    from app.game_engine.talents import TalentConfig
    from app.services.content.seeding import ensure_published
    from app.services.content.types import abilities as at
    from app.services.content.types.balance import get_published_balance

    created = 0
    cfg = await get_published_balance(session, "talents", TalentConfig)
    for arch, values in load_yaml("skills/_archetypes.yaml").items():
        await l10n.seed_values(session, f"talent_archetype.{arch}.name", values, namespace="talent")
    for class_code in CLASS_CODES:
        doc = load_yaml(f"skills/{class_code}.yaml")
        class_doc = load_yaml(f"classes/{class_code}.yaml")
        for i, a in enumerate(doc["abilities"]):
            await _texts(session, f"ability.{a['code']}", a["l10n"], "ability")
            rank = {
                "rank": 1,
                "cost": a.get("cost"),
                "cooldown_s": a.get("cooldown_s", 0),
                "cast_time_s": a.get("cast_time_s", 0),
                "effects": a["effects"],
            }
            created += await ensure_published(
                session,
                at.ABILITY_TYPE,
                a["code"],
                {
                    "owner_type": "class",
                    "owner_code": class_code,
                    "ability_type": a["type"],
                    "unlock_level": a["unlock_level"],
                    "target_rule": a.get("target", "self"),
                    "tags": a.get("tags", []),
                    "ranks": [rank],
                    "trigger": _trigger_of(a["effects"]),
                    "sort_order": i,
                },
            )
        for ti, tree in enumerate(doc["trees"]):
            tree_code = f"{class_code}_{tree['code']}"
            await l10n.seed_values(session, f"talent_tree.{tree_code}.name", tree["l10n"]["name"], namespace="talent")
            await l10n.seed_values(session, f"talent_tree.{tree_code}.focus", tree["l10n"]["focus"], namespace="talent")
            created += await ensure_published(
                session,
                at.TALENT_TREE_TYPE,
                tree_code,
                {"base_class_code": class_code, "focus_key": f"talent_tree.{tree_code}.focus", "sort_order": ti},
            )
            for slot in cfg.layout:
                focus = tree["focus"][slot.focus]
                created += await ensure_published(
                    session,
                    at.TALENT_NODE_TYPE,
                    f"{tree_code}_{slot.slot}",
                    {
                        "tree_code": tree_code,
                        "tier": slot.tier,
                        "slot": slot.slot,
                        "max_rank": slot.max_rank,
                        "required_points_in_tree": cfg.tier_points[slot.tier],
                        "required_level": 1,
                        "is_capstone": False,
                        "requires": [f"{tree_code}_{r}" for r in slot.requires],
                        "archetype_key": f"talent_archetype.{focus['archetype']}.name",
                        "effects": focus["effects"],
                    },
                )
            cap = tree["capstone"]
            await _texts(session, f"talent_node.{cap['code']}", cap["l10n"], "talent")
            last_slot = cfg.layout[-1].slot
            created += await ensure_published(
                session,
                at.TALENT_NODE_TYPE,
                cap["code"],
                {
                    "tree_code": tree_code,
                    "tier": 6,
                    "slot": "capstone",
                    "max_rank": 1,
                    "required_points_in_tree": cfg.capstone.required_points_in_tree,
                    "required_level": cfg.capstone.required_level,
                    "is_capstone": True,
                    "requires": [f"{tree_code}_{last_slot}"],
                    "archetype_key": None,
                    "effects": cap["effects"],
                },
            )
        for branch in class_doc["branches"]:
            for spec in branch["specializations"]:
                aw = spec["awakening"]
                await _texts(session, f"awakening.{aw['code']}", aw["l10n"], "awakening")
                created += await ensure_published(
                    session,
                    at.AWAKENING_TYPE,
                    aw["code"],
                    {"specialization_code": spec["code"], "required_level": 600, "effects": aw["effects"]},
                )
        mastery_code = f"{class_code}_mastery"
        names = class_doc["l10n"]["name"]
        await l10n.seed_values(
            session,
            f"mastery.{mastery_code}.name",
            {loc: pat.replace("{name}", names[loc]) for loc, pat in MASTERY_NAME_PATTERNS.items()},
            namespace="mastery",
        )
        created += await ensure_published(
            session,
            at.MASTERY_TYPE,
            mastery_code,
            {
                "base_class_code": class_code,
                "required_level": 1000,
                "cosmetic_code": f"aura_{class_code}_eternal",
                "effects": [
                    {
                        "effect_type": "STAT_PERCENT",
                        "params": {"stat": class_doc["stat_weights"]["primary"], "percent": 2},
                    }
                ],
            },
        )
    return created


async def seed_passive_profiles(session: AsyncSession) -> int:
    from app.services.content.seeding import ensure_published
    from app.services.content.types.afk_profiles import PASSIVE_PROFILE_TYPE

    created = 0
    order: dict[str, int] = {}
    for prof in load_yaml("profiles/passive_profiles.yaml")["profiles"]:
        order[prof["class"]] = order.get(prof["class"], -1) + 1
        await _texts(session, f"passive_profile.{prof['code']}", prof["l10n"], "passive_profile")
        created += await ensure_published(
            session,
            PASSIVE_PROFILE_TYPE,
            prof["code"],
            {
                "base_class_code": prof["class"],
                "sort_order": order[prof["class"]],
                "defaults": prof["defaults"],
                "rules": prof["rules"],
                "effects": prof["effects"],
            },
        )
    return created


STEPS: list[tuple[str, SeedStep]] = [
    ("rbac", seed_rbac),
    ("localization", seed_localization_files),
    ("balance", seed_balance),
    ("races", seed_races),
    ("classes", seed_classes),
    ("skills", seed_skills),
    ("passive_profiles", seed_passive_profiles),
]


async def run_all(session: AsyncSession) -> dict[str, int]:
    results: dict[str, int] = {}
    for name, step in STEPS:
        results[name] = await step(session)
        await session.flush()
        log.info("seed_step", extra={"step": name, "written": results[name]})
    await session.commit()
    return results
