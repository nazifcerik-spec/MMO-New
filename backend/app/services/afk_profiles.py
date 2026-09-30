"""Player combat/AFK strategy profiles, strategy resolution (passive-only / tactics / hybrid) and previews."""

import zlib
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.content.loader import load_yaml
from app.core.errors import ConflictError, ValidationFailedError
from app.game_engine.combat.engine import simulate
from app.game_engine.combat.models import CombatantSnapshot, CombatConfig, CombatInput, CombatStrategy
from app.game_engine.combat.rules import (
    CONDITION_KINDS,
    MAX_CONDITIONS,
    OPS,
    RuleSet,
    RuleValidationError,
    rule_selector,
    validate_rules,
)
from app.game_engine.combat.training import TrainingEncounter, training_pack
from app.localization.service import resolve_text_map
from app.models.character import Character
from app.models.classes import BaseClass
from app.models.profiles import CharacterAfkProfile, PassiveProfile
from app.services import audit, combat_snapshot
from app.services.content.types.abilities import AbilityLimits
from app.services.content.types.afk_profiles import (
    RISK_LEVELS,
    TARGET_PRIORITIES,
    CombatModes,
    RiskProfiles,
    template_rules,
)
from app.services.content.types.balance import get_published_balance

RARITIES = ("worn", "common", "fine", "rare", "epic", "legendary", "mythic", "relic")
# Providers of available potion counts (inventory, Phase 16).
POTION_PROVIDERS: list[Any] = []


class LootFilter(BaseModel):
    """Contract for loot filtering (applied at AFK claim, Phase 16); auto-salvage can be enabled later."""

    model_config = ConfigDict(extra="forbid")

    min_rarity: Literal["worn", "common", "fine", "rare", "epic", "legendary", "mythic", "relic"] = "common"
    categories: list[str] = Field(default_factory=list, max_length=12)
    min_tier: int = Field(default=0, ge=0, le=10)
    class_tags: list[str] = Field(default_factory=list, max_length=9)
    keep_materials: bool = True
    auto_salvage: bool = False


class ProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preset_code: str | None = Field(default=None, max_length=32)
    mode: Literal["PASSIVE_ONLY", "ACTIVE_TACTICS", "HYBRID"] | None = None
    stance: str | None = Field(default=None, max_length=32)
    target_priority: str | None = Field(default=None, max_length=16)
    potion_threshold_pct: float | None = Field(default=None, ge=0, le=100)
    risk_level: str | None = Field(default=None, max_length=16)
    passive_profile_code: str | None = Field(default=None, max_length=96)
    loot_filter: dict[str, Any] | None = None
    tactics: list[dict[str, Any]] | None = None


def presets() -> dict[str, dict[str, Any]]:
    return dict(load_yaml("system/afk_presets.yaml")["presets"])


async def class_profiles(db: AsyncSession, class_code: str) -> list[PassiveProfile]:
    return list(
        (
            await db.execute(
                select(PassiveProfile)
                .where(PassiveProfile.base_class_code == class_code, PassiveProfile.status == "published")
                .order_by(PassiveProfile.sort_order, PassiveProfile.code)
            )
        ).scalars()
    )


async def get_profile(db: AsyncSession, character: Character, *, for_update: bool = False) -> CharacterAfkProfile:
    stmt = select(CharacterAfkProfile).where(CharacterAfkProfile.character_id == character.id)
    if for_update:
        stmt = stmt.with_for_update()
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None:
        base = await db.get(BaseClass, character.base_class_id)
        assert base is not None
        profiles = await class_profiles(db, base.code)
        default = profiles[0] if profiles else None
        d = default.defaults if default else {}
        modes = await get_published_balance(db, "combat_modes", CombatModes)
        row = CharacterAfkProfile(
            character_id=character.id,
            mode=modes.default_mode,
            stance=d.get("stance", "efficient"),
            target_priority=d.get("target_priority", "lowest_hp"),
            potion_threshold_pct=d.get("potion_threshold_pct", 40),
            risk_level="balanced",
            passive_profile_code=default.code if default else None,
            loot_filter=LootFilter().model_dump(),
            tactics=[],
        )
        db.add(row)
        await db.flush()
    return row


async def update_profile(
    db: AsyncSession, *, character: Character, update: ProfileUpdate, expected_version: int, actor_id: int
) -> CharacterAfkProfile:
    row = await get_profile(db, character, for_update=True)
    if row.version != expected_version:
        raise ConflictError(
            "Profile changed elsewhere; reload", code="version_conflict", details={"current_version": row.version}
        )
    combat_cfg = await combat_snapshot.load_combat_config(db)
    before = _as_dict(row)
    fields = update.model_dump(exclude_unset=True)
    if update.preset_code:
        preset = presets().get(update.preset_code)
        if preset is None:
            raise ValidationFailedError("Unknown preset", code="invalid_preset")
        fields = {**preset, **{k: v for k, v in fields.items() if k != "preset_code"}}
        fields["preset_code"] = update.preset_code
    elif fields:
        fields.setdefault("preset_code", None)
    if fields.get("mode") is not None:
        modes = await get_published_balance(db, "combat_modes", CombatModes)
        if fields["mode"] not in modes.enabled_modes:
            raise ValidationFailedError("Combat mode is disabled", code="mode_disabled")
    if "stance" in fields and fields["stance"] not in combat_cfg.stances:
        raise ValidationFailedError("Unknown stance", code="invalid_stance")
    if "target_priority" in fields and fields["target_priority"] not in TARGET_PRIORITIES:
        raise ValidationFailedError("Unknown target priority", code="invalid_target_priority")
    if "risk_level" in fields and fields["risk_level"] not in RISK_LEVELS:
        raise ValidationFailedError("Unknown risk level", code="invalid_risk")
    if fields.get("passive_profile_code"):
        base = await db.get(BaseClass, character.base_class_id)
        codes = {p.code for p in await class_profiles(db, base.code if base else "")}
        if fields["passive_profile_code"] not in codes:
            raise ValidationFailedError("Profile does not belong to your class", code="invalid_passive_profile")
    if "loot_filter" in fields and fields["loot_filter"] is not None:
        try:
            fields["loot_filter"] = LootFilter.model_validate(fields["loot_filter"]).model_dump()
        except ValidationError as exc:
            raise ValidationFailedError("Invalid loot filter", code="invalid_loot_filter") from exc
    if "tactics" in fields and fields["tactics"] is not None:
        for check in TACTICS_VALIDATORS:
            await check(db, character, fields["tactics"])
    for key, value in fields.items():
        if value is not None or key in ("preset_code", "passive_profile_code"):
            setattr(row, key, value)
    await db.flush()
    await audit.record(
        db,
        actor_id=actor_id,
        action="afk_profile.update",
        entity_type="character",
        entity_id=character.id,
        meta={"diff": audit.diff(before, _as_dict(row))},
    )
    return row


# Registered by the Active Tactics module (Phase 11): async (db, character, rules) -> None, raising on errors.
TACTICS_VALIDATORS: list[Any] = []


def _as_dict(row: CharacterAfkProfile) -> dict[str, Any]:
    return {
        k: getattr(row, k)
        for k in (
            "preset_code",
            "mode",
            "stance",
            "target_priority",
            "potion_threshold_pct",
            "risk_level",
            "passive_profile_code",
            "loot_filter",
            "tactics",
        )
    }


async def potion_count(db: AsyncSession, character: Character) -> int:
    total = 0
    for provider in POTION_PROVIDERS:
        total += int(await provider(db, character))
    return total


def strategy_for(row: CharacterAfkProfile, potions: int) -> CombatStrategy:
    return CombatStrategy(
        mode=row.mode,
        stance=row.stance,
        target_priority=row.target_priority,
        potion_threshold_pct=row.potion_threshold_pct,
        potions=potions,
        tactics=tuple(row.tactics or ()),
    )


async def resolved_rules(
    db: AsyncSession, row: CharacterAfkProfile, *, encounter_type: str, tactics_override: RuleSet | None = None
) -> tuple[RuleSet, list[dict[str, Any]]]:
    """(rules, extra identity effects) for this encounter type.

    PASSIVE_ONLY → passive profile rules; ACTIVE_TACTICS → player tactics; HYBRID → passive-first, player tactics
    only in configured decision encounters (boss/arena), so no constant input is required."""
    modes = await get_published_balance(db, "combat_modes", CombatModes)
    profile = None
    if row.passive_profile_code:
        profile = (
            await db.execute(select(PassiveProfile).where(PassiveProfile.code == row.passive_profile_code))
        ).scalar_one_or_none()
    extra = list(profile.effects) if profile else []
    passive_rules = validate_rules(profile.rules) if profile else RuleSet()
    tactics = tactics_override or validate_rules(row.tactics or [], max_rules=modes.max_rules)
    if tactics_override is not None:
        return tactics, extra
    decision = encounter_type in modes.tactics_encounter_types
    if row.mode == "ACTIVE_TACTICS" or (row.mode == "HYBRID" and decision and tactics.rules):
        return tactics, extra
    return passive_rules, extra


def with_extra_effects(snap: CombatantSnapshot, extra: list[dict[str, Any]]) -> CombatantSnapshot:
    return snap.model_copy(update={"effects": (*snap.effects, *extra)}) if extra else snap


async def preview(
    db: AsyncSession,
    *,
    character: Character,
    fights: int,
    potions: int | None,
    boss: bool,
    locale: str,
    enemies_count: int | None = None,
    tactics_override: RuleSet | None = None,
) -> dict[str, Any]:
    row = await get_profile(db, character)
    cfg: CombatConfig = await combat_snapshot.load_combat_config(db)
    training = await get_published_balance(db, "training_encounter", TrainingEncounter)
    risks = await get_published_balance(db, "risk_profiles", RiskProfiles)
    risk = risks.profiles[row.risk_level]
    snap = await combat_snapshot.character_snapshot(db, character)
    rules, extra = await resolved_rules(
        db, row, encounter_type="boss" if boss else "normal", tactics_override=tactics_override
    )
    snap = with_extra_effects(snap, extra)
    n_potions = potions if potions is not None else await potion_count(db, character)
    strategy = strategy_for(row, n_potions)
    usage: dict[str, dict[str, int]] = {}
    wins = deaths = 0
    total_time = total_taken = total_potions = total_dealt = 0.0
    for i in range(fights):
        enemies = training_pack(
            training, character.level, power_percent=risk.enemy_power_percent, count=1 if boss else enemies_count
        )
        if boss:
            enemies = (
                enemies[0].model_copy(
                    update={"is_boss": True, "stats": {**enemies[0].stats, "max_hp": enemies[0].stats["max_hp"] * 4}}
                ),
            )
        seed = zlib.crc32(f"preview:{character.id}:{i}".encode())
        result = simulate(
            CombatInput(players=(snap,), enemies=enemies, strategy=strategy, seed=seed),
            cfg,
            selector=rule_selector(rules, usage),
        )
        me = result.combatants[0]
        wins += result.outcome == "win"
        deaths += not me.alive
        total_time += result.elapsed_s
        total_taken += me.damage_taken
        total_dealt += me.damage_dealt
        total_potions += me.potions_used
    per_rule = usage.get(snap.id, {})
    labels = await resolve_text_map(db, [f"ability.{r.use.ability}.name" for r in rules.rules if r.use.ability], locale)
    return {
        "fights": fights,
        "win_rate": round(wins / fights, 3),
        "death_rate": round(deaths / fights, 3),
        "avg_duration_s": round(total_time / fights, 2),
        "avg_damage_taken": round(total_taken / fights, 1),
        "avg_damage_dealt": round(total_dealt / fights, 1),
        "avg_potions_used": round(total_potions / fights, 2),
        "dps": round(total_dealt / max(total_time, 1e-9), 2),
        "mode": row.mode,
        "boss": boss,
        "draft": tactics_override is not None,
        "rules": [
            {
                "index": i,
                "ability": r.use.ability,
                "tag": r.use.tag,
                "name": labels.get(f"ability.{r.use.ability}.name") if r.use.ability else r.use.tag,
                "uses": per_rule.get(str(i), 0),
            }
            for i, r in enumerate(rules.rules)
        ],
        "fallback_basic_attacks": per_rule.get("fallback", 0),
    }


async def options(db: AsyncSession, character: Character, locale: str) -> dict[str, Any]:
    cfg = await combat_snapshot.load_combat_config(db)
    base = await db.get(BaseClass, character.base_class_id)
    profiles = await class_profiles(db, base.code if base else "")
    modes = await get_published_balance(db, "combat_modes", CombatModes)
    limits = await get_published_balance(db, "ability_limits", AbilityLimits)
    kit = await combat_snapshot.usable_abilities(db, character)
    kit_tags = sorted({t for a in kit for t in a.tags})
    keys = [
        *(a.name_key for a in kit),
        *(f"stance.{s}.name" for s in cfg.stances),
        *(f"stance.{s}.description" for s in cfg.stances),
        *(f"target_priority.{t}.name" for t in TARGET_PRIORITIES),
        *(f"risk.{r}.name" for r in RISK_LEVELS),
        *(f"afk_preset.{p}.name" for p in presets()),
        *(p.name_key for p in profiles),
        *(p.description_key or "" for p in profiles),
    ]
    text = await resolve_text_map(db, [k for k in keys if k], locale)
    risks = await get_published_balance(db, "risk_profiles", RiskProfiles)
    return {
        "stances": [
            {
                "code": s,
                "name": text[f"stance.{s}.name"],
                "description": text[f"stance.{s}.description"],
                **cfg.stances[s].model_dump(),
            }
            for s in cfg.stances
        ],
        "target_priorities": [{"code": t, "name": text[f"target_priority.{t}.name"]} for t in TARGET_PRIORITIES],
        "risk_levels": [
            {"code": r, "name": text[f"risk.{r}.name"], **risks.profiles[r].model_dump()} for r in RISK_LEVELS
        ],
        "presets": [{"code": c, "name": text[f"afk_preset.{c}.name"], **p} for c, p in presets().items()],
        "passive_profiles": [
            {
                "code": p.code,
                "name": text[p.name_key],
                "description": text.get(p.description_key or ""),
                "defaults": p.defaults,
                "rules": p.rules,
            }
            for p in profiles
        ],
        "rarities": list(RARITIES),
        "modes": list(modes.enabled_modes),
        "default_mode": modes.default_mode,
        "tactics": {
            "max_rules": modes.max_rules,
            "max_conditions": MAX_CONDITIONS,
            "max_core_actives": limits.max_core_actives,
            "max_ultimates": limits.max_ultimates,
            "decision_encounters": list(modes.tactics_encounter_types),
            "condition_kinds": list(CONDITION_KINDS),
            "ops": list(OPS),
            "tags": kit_tags,
            "abilities": [
                {
                    "code": a.code,
                    "name": text[a.name_key],
                    "type": a.ability_type,
                    "tags": a.tags,
                    "cooldown_s": a.ranks[0].get("cooldown_s", 0),
                }
                for a in kit
            ],
            "template": template_rules(modes, set(kit_tags)),
        },
    }


def profile_out(row: CharacterAfkProfile) -> dict[str, Any]:
    return {**_as_dict(row), "version": row.version}


Mode = Literal["PASSIVE_ONLY", "ACTIVE_TACTICS", "HYBRID"]
_ = RuleValidationError  # re-exported for API error mapping
