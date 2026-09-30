"""Build immutable combat snapshots from live DB state (character build → CombatantSnapshot).

The snapshot bakes static stats (stat calculator) and carries every dynamic effect from race, class, branch,
specialization, awakening, mastery and talents (rank-scaled) + unlocked abilities, so replays never touch
live content again. Support Solo Accord is applied here when fighting alone."""

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.game_engine.combat.models import AbilitySnapshot, CombatantSnapshot, CombatConfig, ResourceSnapshot
from app.game_engine.effects import SoloAccord, validate_effect
from app.game_engine.talents import scale_effect
from app.models.abilities import AbilityDefinition, AwakeningDefinition, MasteryDefinition, TalentNode
from app.models.character import Character
from app.models.classes import BaseClass, ClassBranch, ClassResource, Specialization
from app.models.race import Race
from app.services import classes, progression, talents
from app.services.content import service as content_service
from app.services.content.types.balance import get_published_balance

STATIC_TYPES = {"STAT_FLAT", "STAT_PERCENT"}
ACTIVE_TYPES = {"ACTIVE", "ULTIMATE", "STANCE"}
# Extra effect sources (e.g. equipment in Phase 16) contribute dynamic effects here.
EFFECT_PROVIDERS: list[Any] = []
WEAPON_PROVIDERS: list[Any] = []


async def load_combat_config(db: AsyncSession) -> CombatConfig:
    return await get_published_balance(db, "combat", CombatConfig)


def dynamic(effects: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [e for e in effects if e["effect_type"] not in STATIC_TYPES]


def apply_solo_accord(stats: dict[str, float], effects: list[dict[str, Any]], party_size: int) -> dict[str, float]:
    """Outside a party, convert conversion% of summed source stats into the target stats."""
    if party_size > 1:
        return stats
    out = dict(stats)
    for e in effects:
        if e["effect_type"] != "SOLO_ACCORD":
            continue
        p = validate_effect(e)
        assert isinstance(p, SoloAccord)
        support_power = sum(stats.get(s, 0.0) for s in p.source_stats)
        bonus = support_power * p.conversion_percent / 100.0
        for t in p.target_stats:
            out[t] = out.get(t, 0.0) + bonus
    return out


async def character_snapshot(
    db: AsyncSession, character: Character, *, party_size: int = 1, snapshot_id: str | None = None
) -> CombatantSnapshot:
    row = await classes.get_progression_row(db, character)
    sheet = await progression.stat_sheet(db, character)
    base = await db.get(BaseClass, character.base_class_id)
    race = await db.get(Race, character.race_id)
    assert base is not None and race is not None
    effects: list[dict[str, Any]] = [*dynamic(race.effects), *dynamic(base.base_effects)]
    if base.solo_accord:
        effects.append({"effect_type": "SOLO_ACCORD", "params": base.solo_accord})
    if row.branch_code:
        b = (await db.execute(select(ClassBranch).where(ClassBranch.code == row.branch_code))).scalar_one()
        effects += dynamic(b.effects)
    if row.specialization_code:
        s = (
            await db.execute(select(Specialization).where(Specialization.code == row.specialization_code))
        ).scalar_one()
        effects += dynamic(s.effects)
        if row.awakened_at:
            aw = (
                await db.execute(select(AwakeningDefinition).where(AwakeningDefinition.specialization_code == s.code))
            ).scalar_one_or_none()
            if aw:
                effects += dynamic(aw.effects)
    if row.mastery_at:
        m = (
            await db.execute(select(MasteryDefinition).where(MasteryDefinition.base_class_code == base.code))
        ).scalar_one_or_none()
        if m:
            effects += dynamic(m.effects)
    alloc = await talents.allocation(db, character.id)
    if alloc:
        nodes = list((await db.execute(select(TalentNode).where(TalentNode.code.in_(list(alloc))))).scalars())
        for n in sorted(nodes, key=lambda n: n.code):
            effects += dynamic([scale_effect(e, alloc[n.code]) for e in n.effects])
    for provider in EFFECT_PROVIDERS:
        effects += dynamic(await provider(db, character))
    weapon_family = None
    for wp in WEAPON_PROVIDERS:
        weapon_family = await wp(db, character) or weapon_family
    stats = apply_solo_accord(sheet.finals(), effects, party_size)
    resources = list((await db.execute(select(ClassResource).where(ClassResource.code.in_(base.resources)))).scalars())
    by_code = {r.code: r for r in resources}
    owners = {("class", base.code)}
    if row.branch_code:
        owners.add(("branch", row.branch_code))
    if row.specialization_code:
        owners.add(("specialization", row.specialization_code))
    ability_rows = list(
        (
            await db.execute(
                select(AbilityDefinition)
                .where(
                    AbilityDefinition.status == "published",
                    AbilityDefinition.unlock_level <= character.level,
                    AbilityDefinition.ability_type.in_(sorted(ACTIVE_TYPES)),
                )
                .order_by(AbilityDefinition.sort_order)
            )
        ).scalars()
    )
    abilities = []
    for a in ability_rows:
        if (a.owner_type, a.owner_code) not in owners:
            continue
        rank = a.ranks[0]
        cost = rank.get("cost") or {}
        abilities.append(
            AbilitySnapshot(
                code=a.code,
                ability_type=a.ability_type,
                target_rule=a.target_rule,
                tags=tuple(a.tags),
                cost_resource=cost.get("resource"),
                cost_amount=float(cost.get("amount", 0)),
                cooldown_s=float(rank.get("cooldown_s", 0)),
                cast_time_s=float(rank.get("cast_time_s", 0)),
                effects=tuple(rank["effects"]),
            )
        )
    power_stat = "spell_power" if base.main_damage_stat in ("INT", "WIS", "SPI") else "attack_power"
    role = {"combat": "dps", "support": "support"}[base.category]
    return CombatantSnapshot(
        id=snapshot_id or f"c{character.id}",
        code=base.code,
        side="players",
        level=character.level,
        stats={k: round(v, 6) for k, v in sorted(stats.items())},
        resources=tuple(
            ResourceSnapshot(
                code=c,
                max=by_code[c].max_value,
                start=by_code[c].start_value,
                regen_per_s=by_code[c].regen_per_s,
                decay_per_s=by_code[c].decay_per_s,
            )
            for c in base.resources
            if c in by_code
        ),
        primary_resource=base.resources[0] if base.resources else None,
        effects=tuple(e for e in effects if e["effect_type"] != "SOLO_ACCORD"),
        abilities=tuple(abilities),
        weapon_family=weapon_family,
        power_stat=power_stat,
        base_damage_type="physical" if power_stat == "attack_power" else "magic",
        role=role,
        tags=(base.code, *(t for t in [row.branch_code, row.specialization_code] if t)),
    )


async def content_version(db: AsyncSession) -> int:
    return await content_service.current_release_version(db)
