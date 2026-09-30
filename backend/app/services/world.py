"""World service: published zone listing/detail with requirement checks, and immutable ZoneBundle loading
for encounter generation (AFK sessions snapshot the bundle)."""

from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.game_engine.world import DropTableDef, EnemyDef, EnemyScaling, TierScaling, ZoneBundle, boss_effects
from app.localization.service import resolve_text_map
from app.models.character import Character
from app.models.world import (
    BossTemplate,
    DropTable,
    EncounterTemplate,
    EnemyAbilityProfile,
    EnemyTemplate,
    Zone,
    ZoneTier,
)
from app.services import classes
from app.services.content import service as content_service
from app.services.content.types.afk_profiles import RiskProfiles
from app.services.content.types.balance import get_published_balance

# Requirement providers registered by later systems (zone clears Phase 13, quests Phase 22):
# async (db, character, code) -> bool. With no provider the requirement is unmet (deny by default).
ZONE_CLEAR_PROVIDERS: list[Any] = []
QUEST_PROVIDERS: list[Any] = []
STAGE_FIELDS = {"promotion": "branch_code", "specialization": "specialization_code", "awakening": "awakened_at"}
MAX_PAGE = 50


def _published[T](model: type[T]) -> Select[T]:
    m: Any = model
    return select(model).where(m.status == "published", m.deleted_at.is_(None))


async def _any(providers: list[Any], db: AsyncSession, character: Character, code: str) -> bool:
    for p in providers:
        if await p(db, character, code):
            return True
    return False


async def unmet_requirements(db: AsyncSession, character: Character, zone: Zone) -> list[dict[str, Any]]:
    unmet: list[dict[str, Any]] = []
    if character.level < zone.min_level:
        unmet.append({"kind": "min_level", "value": zone.min_level})
    row = None
    for r in zone.requirements:
        kind = r["kind"]
        if kind == "min_level" and character.level < r["value"] and r["value"] != zone.min_level:
            unmet.append(r)
        elif kind == "zone_cleared" and not await _any(ZONE_CLEAR_PROVIDERS, db, character, r["code"]):
            unmet.append(r)
        elif kind == "quest" and not await _any(QUEST_PROVIDERS, db, character, r["code"]):
            unmet.append(r)
        elif kind == "class_stage":
            row = row or await classes.get_progression_row(db, character)
            field = STAGE_FIELDS.get(r["code"], "mastery_at")
            if getattr(row, field, None) is None:
                unmet.append(r)
    return unmet


async def list_zones(
    db: AsyncSession, locale: str, *, character: Character | None = None, after: int | None = None, limit: int = 20
) -> dict[str, Any]:
    limit = max(1, min(limit, MAX_PAGE))
    stmt = _published(Zone).order_by(Zone.sort_order, Zone.id)
    if after is not None:
        stmt = stmt.where(Zone.sort_order > after)
    zones = list((await db.execute(stmt.limit(limit + 1))).scalars())
    more = len(zones) > limit
    zones = zones[:limit]
    tiers = {t.code: t for t in (await db.execute(_published(ZoneTier))).scalars()}
    keys = [z.name_key for z in zones] + [t.name_key for t in tiers.values()]
    text = await resolve_text_map(db, keys, locale)
    items = []
    for z in zones:
        item: dict[str, Any] = {
            "code": z.code,
            "name": text[z.name_key],
            "tier": tiers[z.tier_code].tier if z.tier_code in tiers else None,
            "tier_name": text.get(tiers[z.tier_code].name_key) if z.tier_code in tiers else None,
            "min_level": z.min_level,
            "recommended_level": z.recommended_level,
            "max_level": z.max_level,
            "danger_rating": z.danger_rating,
            "environment_tags": z.environment_tags,
        }
        if character is not None:
            unmet = await unmet_requirements(db, character, z)
            item["eligible"] = not unmet
            item["unmet"] = unmet
        items.append(item)
    return {"items": items, "next_cursor": zones[-1].sort_order if more and zones else None}


async def get_zone(db: AsyncSession, code: str) -> Zone:
    zone = (await db.execute(_published(Zone).where(Zone.code == code))).scalar_one_or_none()
    if zone is None:
        raise NotFoundError("Zone not found", code="zone_not_found")
    return zone


async def zone_detail(db: AsyncSession, code: str, locale: str, character: Character | None = None) -> dict[str, Any]:
    zone = await get_zone(db, code)
    tier = (await db.execute(select(ZoneTier).where(ZoneTier.code == zone.tier_code))).scalar_one()
    enc_codes = [p["encounter_code"] for p in zone.encounter_pool]
    encounters = list(
        (await db.execute(_published(EncounterTemplate).where(EncounterTemplate.code.in_(enc_codes)))).scalars()
    )
    enemy_codes = sorted({m["enemy_code"] for e in encounters for m in e.members})
    enemies = list((await db.execute(_published(EnemyTemplate).where(EnemyTemplate.code.in_(enemy_codes)))).scalars())
    bosses = list(
        (
            await db.execute(
                _published(BossTemplate).where(BossTemplate.code.in_([b["boss_code"] for b in zone.boss_pool]))
            )
        ).scalars()
    )
    drops = None
    if zone.drop_table_code:
        drops = (await db.execute(select(DropTable).where(DropTable.code == zone.drop_table_code))).scalar_one_or_none()
    keys = [zone.name_key, tier.name_key, *(e.name_key for e in enemies), *(b.name_key for b in bosses)]
    if zone.description_key:
        keys.append(zone.description_key)
    text = await resolve_text_map(db, keys, locale)
    risks = await get_published_balance(db, "risk_profiles", RiskProfiles)
    risk_text = await resolve_text_map(db, [f"risk.{r}.name" for r in risks.profiles], locale)
    out: dict[str, Any] = {
        "code": zone.code,
        "name": text[zone.name_key],
        "description": text.get(zone.description_key or ""),
        "tier": tier.tier,
        "tier_name": text[tier.name_key],
        "rarity_band": tier.rarity_band,
        "min_level": zone.min_level,
        "recommended_level": zone.recommended_level,
        "max_level": zone.max_level,
        "danger_rating": zone.danger_rating,
        "environment_tags": zone.environment_tags,
        "loot_modifiers": zone.loot_modifiers,
        "profession_nodes": zone.profession_nodes,
        "boss_chance_pct": zone.boss_chance_pct,
        "enemies": [
            {
                "code": e.code,
                "name": text[e.name_key],
                "rank": e.rank,
                "archetype": e.archetype,
                "damage_type": e.damage_type,
            }
            for e in enemies
        ],
        "bosses": [
            {"code": b.code, "name": text[b.name_key], "archetype": b.archetype, "damage_type": b.damage_type}
            for b in bosses
        ],
        "drops": sorted(
            {
                (e["kind"], e.get("tier"), e.get("rarity"))
                for e in (drops.entries if drops else [])
                if e["kind"] != "nothing"
            },
            key=str,
        ),
        "risk_profiles": [
            {"code": c, "name": risk_text[f"risk.{c}.name"], **p.model_dump()} for c, p in risks.profiles.items()
        ],
    }
    out["drops"] = [{"kind": k, "tier": t, "rarity": r} for k, t, r in out["drops"]]
    if character is not None:
        unmet = await unmet_requirements(db, character, zone)
        out["eligible"], out["unmet"] = not unmet, unmet
    return out


async def load_bundle(db: AsyncSession, code: str) -> ZoneBundle:
    """Resolve a published zone into an immutable, self-contained bundle (JSON-serializable)."""
    zone = await get_zone(db, code)
    tier = (await db.execute(select(ZoneTier).where(ZoneTier.code == zone.tier_code))).scalar_one()
    enc_weights = {p["encounter_code"]: p["weight"] for p in zone.encounter_pool}
    encounters = list(
        (await db.execute(_published(EncounterTemplate).where(EncounterTemplate.code.in_(list(enc_weights))))).scalars()
    )
    boss_weights = {b["boss_code"]: b["weight"] for b in zone.boss_pool}
    bosses = list(
        (await db.execute(_published(BossTemplate).where(BossTemplate.code.in_(list(boss_weights))))).scalars()
    )
    enemy_codes = {m["enemy_code"] for e in encounters for m in e.members} | {
        a["enemy_code"] for b in bosses for a in b.adds
    }
    enemies = list((await db.execute(_published(EnemyTemplate).where(EnemyTemplate.code.in_(enemy_codes)))).scalars())
    profile_codes = {e.ability_profile_code for e in enemies if e.ability_profile_code}
    profile_codes |= {b.ability_profile_code for b in bosses if b.ability_profile_code}
    profiles = {
        p.code: p
        for p in (
            await db.execute(_published(EnemyAbilityProfile).where(EnemyAbilityProfile.code.in_(profile_codes)))
        ).scalars()
    }
    table_codes = {zone.drop_table_code, *(b.drop_table_code for b in bosses)} - {None}
    tables = {
        t.code: DropTableDef(rolls=t.rolls, entries=tuple(t.entries))
        for t in (await db.execute(_published(DropTable).where(DropTable.code.in_(table_codes)))).scalars()
    }

    def enemy_def(
        e: Any, rank: str, extra: list[dict[str, Any]], adds: list[dict[str, Any]], table: str | None
    ) -> EnemyDef:
        prof = profiles.get(e.ability_profile_code or "")
        return EnemyDef(
            code=e.code,
            rank=rank,
            archetype=e.archetype,
            damage_type=e.damage_type,
            stat_mods=e.stat_mods,
            effects=(*e.effects, *(prof.effects if prof else ()), *extra),
            abilities=tuple(prof.abilities) if prof else (),
            rules=tuple(prof.rules) if prof else (),
            tags=tuple(getattr(e, "tags", ()) or ()),
            reward_pct=e.reward_pct,
            adds=tuple(a for a in adds if a["enemy_code"] in enemy_codes),
            drop_table=table,
        )

    defs = {e.code: enemy_def(e, e.rank, [], [], None) for e in enemies}
    for b in bosses:
        defs[b.code] = enemy_def(
            b,
            "boss",
            boss_effects(b.phases, b.enrage_after_s),
            b.adds,
            b.drop_table_code if b.drop_table_code in tables else None,
        )
    valid_encounters = [
        {"code": e.code, "weight": enc_weights[e.code], "members": e.members}
        for e in sorted(encounters, key=lambda e: e.code)
        if all(m["enemy_code"] in defs for m in e.members)
    ]
    if not valid_encounters:
        raise NotFoundError("Zone has no playable encounters", code="zone_not_playable")
    return ZoneBundle(
        code=zone.code,
        tier=tier.tier,
        min_level=zone.min_level,
        max_level=zone.max_level,
        tier_scaling=TierScaling.model_validate(tier.scaling),
        scaling=await get_published_balance(db, "enemy_scaling", EnemyScaling),
        encounters=tuple(valid_encounters),
        bosses=tuple({"code": b.code, "weight": boss_weights[b.code]} for b in sorted(bosses, key=lambda b: b.code)),
        boss_chance_pct=zone.boss_chance_pct,
        enemies=defs,
        drop_tables=tables,
        zone_drop_table=zone.drop_table_code if zone.drop_table_code in tables else None,
        loot_modifiers=zone.loot_modifiers,
        content_version=await content_service.current_release_version(db),
    )
