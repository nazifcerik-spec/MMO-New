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


TIER_NAMES = {"en": "Tier {t}", "tr": "Kademe {t}", "zh-CN": "第{t}阶", "es": "Nivel {t}"}


async def seed_world(session: AsyncSession) -> int:
    """Expand the compact sample world (one zone per tier) into published, validated content entities."""
    from app.services.content.seeding import ensure_published
    from app.services.content.types import world as w

    doc = load_yaml("world/sample_world.yaml")
    created = 0
    for t in doc["tiers"]:
        code = f"t{t['tier']}"
        await l10n_service_seed(
            session, f"zone_tier.{code}.name", {k: v.format(t=t["tier"]) for k, v in TIER_NAMES.items()}, "zone"
        )
        data = {
            "tier": t["tier"],
            "min_level": t["min"],
            "max_level": t["max"],
            "scaling": t["scaling"],
            "rarity_band": t["rarity"],
        }
        created += await ensure_published(session, w.ZONE_TIER_TYPE, code, data)
    for code, prof in doc["ability_profiles"].items():
        await _texts(session, f"enemy_ability_profile.{code}", prof["l10n"], "enemy")
        data = {"abilities": prof["abilities"], "rules": prof["rules"], "effects": []}
        created += await ensure_published(session, w.ENEMY_ABILITY_PROFILE_TYPE, code, data)
    bands = {t["tier"]: t["rarity"] for t in doc["tiers"]}
    for z in doc["zones"]:
        tier, band = z["tier"], bands[z["tier"]]
        gold = (10 * (tier + 1), 25 * (tier + 1))
        zone_drops = {
            "rolls": 2,
            "entries": [
                {"kind": "gold", "weight": 60, "min_qty": gold[0], "max_qty": gold[1]},
                {"kind": "item_pool", "tier": tier, "rarity": band[0], "weight": 30, "chance_pct": 40},
                {"kind": "item_pool", "tier": tier, "rarity": band[-1], "weight": 10, "chance_pct": 15, "rare": True},
                {"kind": "nothing", "weight": 20},
            ],
        }
        boss_drops = {
            "rolls": 3,
            "entries": [
                {"kind": "gold", "weight": 40, "min_qty": gold[1] * 4, "max_qty": gold[1] * 8},
                {"kind": "item_pool", "tier": tier, "rarity": band[-1], "weight": 40, "chance_pct": 60, "rare": True},
                {"kind": "item_pool", "tier": tier, "rarity": band[0], "weight": 20, "boss_only": True},
            ],
        }
        boss = z["boss"]
        for code, table in ((f"{z['code']}_drops", zone_drops), (f"{boss['code']}_drops", boss_drops)):
            created += await ensure_published(session, w.DROP_TABLE_TYPE, code, table)
        for e in z["enemies"]:
            await l10n_service_seed(session, f"enemy.{e['code']}.name", e["l10n"], "enemy")
            data = {
                "family": z["code"],
                "archetype": e["archetype"],
                "rank": e.get("rank", "normal"),
                "damage_type": e.get("damage_type", "physical"),
                "stat_mods": {},
                "ability_profile_code": e["profile"],
                "effects": [],
                "tags": [*z["env"][:1], e["archetype"]],
                "reward_pct": 250 if e.get("rank") == "elite" else 100,
            }
            created += await ensure_published(session, w.ENEMY_TYPE, e["code"], data)
        normal = [e["code"] for e in z["enemies"] if e.get("rank", "normal") == "normal"]
        elite = next(e["code"] for e in z["enemies"] if e.get("rank") == "elite")
        await l10n_service_seed(session, f"boss.{boss['code']}.name", boss["l10n"], "enemy")
        boss_data = {
            "family": z["code"],
            "archetype": boss["archetype"],
            "damage_type": boss.get("damage_type", "physical"),
            "stat_mods": {},
            "ability_profile_code": "boss_warlord",
            "effects": [],
            "phases": [
                {"hp_below_pct": 50, "effects": [{"effect_type": "DAMAGE_MULTIPLIER", "params": {"percent": 25}}]},
                {
                    "hp_below_pct": 25,
                    "effects": [{"effect_type": "SHIELD", "params": {"percent_max_hp": 8, "duration_s": 10}}],
                },
            ],
            "adds": [{"enemy_code": normal[0], "count": 1}] if tier >= 2 else [],
            "enrage_after_s": 300,
            "drop_table_code": f"{boss['code']}_drops",
            "reward_pct": 1000,
        }
        created += await ensure_published(session, w.BOSS_TYPE, boss["code"], boss_data)
        encounters = {
            f"{z['code']}_pack": [
                {"enemy_code": normal[0], "min": 2, "max": 3},
                {"enemy_code": normal[1], "min": 0 + 1, "max": 1},
            ],
            f"{z['code']}_hunters": [{"enemy_code": normal[1], "min": 2, "max": 3}],
            f"{z['code']}_elite": [
                {"enemy_code": elite, "min": 1, "max": 1},
                {"enemy_code": normal[0], "min": 1, "max": 2},
            ],
        }
        for code, members in encounters.items():
            created += await ensure_published(session, w.ENCOUNTER_TYPE, code, {"members": members, "tags": []})
        lo, rec, hi = z["levels"]
        await _texts(session, f"zone.{z['code']}", z["l10n"], "zone")
        zone_data = {
            "tier_code": f"t{tier}",
            "sort_order": tier * 10,
            "min_level": lo,
            "recommended_level": rec,
            "max_level": hi,
            "danger_rating": z["danger"],
            "environment_tags": z["env"],
            "encounter_pool": [
                {"encounter_code": f"{z['code']}_pack", "weight": 60},
                {"encounter_code": f"{z['code']}_hunters", "weight": 30},
                {"encounter_code": f"{z['code']}_elite", "weight": 10},
            ],
            "boss_pool": [{"boss_code": boss["code"], "weight": 1}],
            "boss_chance_pct": 2,
            "loot_modifiers": {"xp_pct": 100, "gold_pct": 100, "drop_pct": 100, "rare_pct": 100},
            "drop_table_code": f"{z['code']}_drops",
            "profession_nodes": z["nodes"],
            "requirements": [{"kind": "min_level", "value": lo}] if lo > 1 else [],
        }
        created += await ensure_published(session, w.ZONE_TYPE, z["code"], zone_data)
    return created


async def seed_items(session: AsyncSession) -> int:
    """Sample affixes/sets/templates (dev/test). Requirements come from the canonical requirement profiles."""
    from app.game_engine.items import ItemRules, suggested_requirements
    from app.services.content.seeding import ensure_published
    from app.services.content.types import items as it
    from app.services.content.types.balance import get_published_balance

    doc = load_yaml("items/sample_items.yaml")
    rules = await get_published_balance(session, "item_rules", ItemRules)
    created = 0
    for a in doc["affixes"]:
        await l10n_service_seed(session, f"affix.{a['code']}.name", a["l10n"], "item")
        data = {k: v for k, v in a.items() if k not in ("code", "l10n")}
        created += await ensure_published(session, it.AFFIX_TYPE, a["code"], data)
    for s in doc["sets"]:
        await l10n_service_seed(session, f"item_set.{s['code']}.name", s["l10n"], "item")
        created += await ensure_published(session, it.ITEM_SET_TYPE, s["code"], {"bonuses": s["bonuses"]})

    def base(t: dict[str, Any], category: str) -> dict[str, Any]:
        return {
            "category": category,
            "tier": t["tier"],
            "min_level": t.get("level", rules.gate(t["tier"]).min_level),
            "rarity": t["rarity"],
            "stack_size": t.get("stack", 1),
            "vendor_value": t.get("vendor", 0),
        }

    for m in doc["materials"]:
        await l10n_service_seed(session, f"item.{m['code']}.name", m["l10n"], "item")
        data = {**base(m, "material"), "sources": [{"kind": "drop"}]}
        created += await ensure_published(session, it.ITEM_TEMPLATE_TYPE, m["code"], data)
    for c in doc["consumables"]:
        await l10n_service_seed(session, f"item.{c['code']}.name", c["l10n"], "item")
        data = {
            **base(c, "consumable"),
            "subcategory": "potion",
            "effects": c["effects"],
            "sources": [{"kind": "vendor"}],
        }
        created += await ensure_published(session, it.ITEM_TEMPLATE_TYPE, c["code"], data)
    for e in doc["equipment"]:
        await l10n_service_seed(session, f"item.{e['code']}.name", e["l10n"], "item")
        data = base(e, e["category"])
        reqs = suggested_requirements(rules, e["profile"], data["min_level"], e["tier"]) if e.get("profile") else {}
        data.update(
            {
                "slot": e["slot"],
                "subcategory": e.get("subcategory"),
                "weapon_family": e.get("weapon_family"),
                "armor_family": e.get("armor_family"),
                "requirement_profile": e.get("profile"),
                "requirements": {"stats": {k: v for k, v in reqs.items() if v > 0}},
                "base_stats": [{"stat": k, "amount": v} for k, v in e.get("base", {}).items()],
                "effects": e.get("effects", []),
                "durability": {"max": e.get("durability", 0)},
                "affix_rules": {
                    "pool": e.get("pool", []),
                    "fixed": e.get("fixed", []),
                    **({} if e.get("pool") or e.get("fixed") else {"max": 0}),
                },
                "unique_effect": e.get("unique"),
                "set_code": e.get("set"),
                "salvage": [{"template_code": code, "min_qty": 1, "max_qty": 3} for code in e.get("salvage", [])],
                "bind_policy": e.get("bind", "none"),
                "tradeable": e.get("tradeable", True),
                "icon": f"items/{e['code']}.svg",
                "sources": e.get("sources", [{"kind": "drop"}]),
            }
        )
        created += await ensure_published(session, it.ITEM_TEMPLATE_TYPE, e["code"], data)
    return created


async def seed_professions(session: AsyncSession) -> int:
    """Canonical 15 professions × 2 specializations, rank names and grandmaster titles (4 locales)."""
    from app.services.content.seeding import ensure_published
    from app.services.content.types.professions import PROFESSION_SPEC_TYPE, PROFESSION_TYPE

    doc = load_yaml("professions/professions.yaml")
    created = 0
    for code, names in doc["ranks"].items():
        await l10n_service_seed(session, f"profession_rank.{code}.name", names, "profession")
    for order, p in enumerate(doc["professions"]):
        await _texts(session, f"profession.{p['code']}", p["l10n"], "profession")
        data = {
            "type": p["type"],
            "tool_kind": p["tool"],
            "stats": p["stats"],
            "sort_order": order,
            "title_key": f"profession.{p['code']}.title",
            "effects": [],
        }
        created += await ensure_published(session, PROFESSION_TYPE, p["code"], data)
        for i, spec in enumerate(p["specs"]):
            await l10n_service_seed(session, f"profession_spec.{spec['code']}.name", spec["l10n"], "profession")
            effects = [
                {"effect_type": "PROFESSION_YIELD_MOD", "params": {"profession": p["code"], "kind": k, "percent": v}}
                for k, v in spec["effects"]
            ]
            data = {"profession_code": p["code"], "sort_order": i, "effects": effects}
            created += await ensure_published(session, PROFESSION_SPEC_TYPE, spec["code"], data)
    return created


async def seed_crafting(session: AsyncSession) -> int:
    """Sample gathering nodes, materials, tools/gadgets, recipes and imbues (validated like editor content)."""
    from app.game_engine.items import ItemRules
    from app.services.content.seeding import ensure_published
    from app.services.content.types import crafting as cr
    from app.services.content.types import items as it
    from app.services.content.types.balance import get_published_balance

    doc = load_yaml("professions/crafting_content.yaml")
    rules = await get_published_balance(session, "item_rules", ItemRules)
    created = 0
    for code, (tier, rarity, vendor, names) in doc["materials"].items():
        await l10n_service_seed(session, f"item.{code}.name", names, "item")
        data = {
            "category": "material",
            "tier": tier,
            "min_level": rules.gate(tier).min_level,
            "rarity": rarity,
            "stack_size": 999,
            "vendor_value": vendor,
            "sources": [{"kind": "drop"}],
        }
        created += await ensure_published(session, it.ITEM_TEMPLATE_TYPE, code, data)
    for t in doc["templates"]:
        await l10n_service_seed(session, f"item.{t['code']}.name", t["l10n"], "item")
        data = {
            "category": t["category"],
            "slot": t.get("slot"),
            "subcategory": t.get("subcategory"),
            "tier": t["tier"],
            "min_level": t["level"],
            "rarity": t["rarity"],
            "stack_size": t.get("stack", 1),
            "vendor_value": t["vendor"],
            "durability": {"max": t.get("durability", 0)},
            "effects": t.get("effects", []),
            "affix_rules": {"pool": t.get("pool", []), **({} if t.get("pool") else {"max": 0})},
            "sources": [{"kind": "craft"}],
        }
        created += await ensure_published(session, it.ITEM_TEMPLATE_TYPE, t["code"], data)
    for code, (prof, tier, entries) in doc["nodes"].items():
        data = {
            "profession_code": prof,
            "tier": tier,
            "entries": [
                {"template_code": m, "weight": w, "min": lo, "max": hi, "rare": rare} for m, w, lo, hi, rare in entries
            ],
        }
        created += await ensure_published(session, cr.GATHERING_NODE_TYPE, code, data)
    for r in doc["recipes"]:
        await l10n_service_seed(session, f"recipe.{r['code']}.name", r["l10n"], "profession")
        data = {
            "profession_code": r["profession"],
            "required_level": r["level"],
            "recipe_rarity": r.get("rarity", "common"),
            "unlock": {"kind": r.get("unlock", "auto")},
            "scroll_template_code": r.get("scroll"),
            "ingredients": [{"template_code": c, "qty": q} for c, q in r["ingredients"]],
            "tool_kind": r.get("tool"),
            "workstation": r.get("workstation"),
            "craft_time_s": r["time"],
            "xp": r["xp"],
            "output": {"template_code": r["output"][0], "qty": r["output"][1]},
            "quality_applies": r.get("quality", True),
            "fail_chance_pct": r.get("fail", 0),
            "fail_return_pct": 50,
        }
        created += await ensure_published(session, cr.RECIPE_TYPE, r["code"], data)
    for im in doc["imbues"]:
        await l10n_service_seed(session, f"imbue.{im['code']}.name", im["l10n"], "profession")
        data = {
            "required_level": im["level"],
            "categories": im["categories"],
            "effects": im["effects"],
            "gold_cost": im["gold"],
            "materials": [{"template_code": c, "qty": q} for c, q in im["materials"]],
        }
        created += await ensure_published(session, cr.IMBUE_TYPE, im["code"], data)
    return created


STEPS: list[tuple[str, SeedStep]] = [
    ("rbac", seed_rbac),
    ("localization", seed_localization_files),
    ("balance", seed_balance),
    ("races", seed_races),
    ("classes", seed_classes),
    ("skills", seed_skills),
    ("passive_profiles", seed_passive_profiles),
    ("professions", seed_professions),
    ("world", seed_world),
    ("items", seed_items),
    ("crafting", seed_crafting),
]


async def run_all(session: AsyncSession) -> dict[str, int]:
    results: dict[str, int] = {}
    for name, step in STEPS:
        results[name] = await step(session)
        await session.flush()
        log.info("seed_step", extra={"step": name, "written": results[name]})
    await session.commit()
    return results
