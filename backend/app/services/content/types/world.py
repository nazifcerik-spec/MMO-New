"""World content types (zone tiers, zones, enemies, ability profiles, encounters, bosses, drop tables) and
publish validators: unknown/unpublished references, empty pools, level ranges, circular or unreachable
prerequisites and 'impossible enemy' sanity warnings."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.game_engine.combat.rules import RuleValidationError, validate_rules
from app.game_engine.effects import EffectValidationError, validate_effects
from app.game_engine.stats import DAMAGE_TYPES
from app.game_engine.world import ENEMY_STATS, EnemyScaling, TierScaling, enemy_stats, sanity_issues
from app.models.world import (
    BossTemplate,
    DropTable,
    EncounterTemplate,
    EnemyAbilityProfile,
    EnemyTemplate,
    Zone,
    ZoneTier,
)
from app.services.content.registry import ContentType, Issue, register
from app.services.content.types.balance import BALANCE_SCHEMAS, get_published_balance

BALANCE_SCHEMAS["enemy_scaling"] = EnemyScaling
CODE = r"^[a-z0-9_]+$"
RARITIES = ("worn", "common", "fine", "rare", "epic", "legendary", "mythic", "relic")
# Checkers for drop references into systems added later (items Phase 14, materials/currencies Phase 16/19):
# async (db, entry) -> Issue | None
DROP_REFERENCE_CHECKERS: list[Any] = []


class _S(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _check_mods(mods: dict[str, float]) -> dict[str, float]:
    for k, v in mods.items():
        if k not in ENEMY_STATS or not -90 <= v <= 500:
            raise ValueError(f"stat_mods.{k} invalid (stats {ENEMY_STATS}, -90..500%)")
    return mods


class ZoneTierData(_S):
    tier: int = Field(ge=0, le=10)
    min_level: int = Field(ge=1, le=1000)
    max_level: int = Field(ge=1, le=1000)
    scaling: TierScaling
    rarity_band: list[Literal["worn", "common", "fine", "rare", "epic", "legendary", "mythic", "relic"]] = Field(
        max_length=4
    )

    @model_validator(mode="after")
    def _range(self) -> "ZoneTierData":
        if self.min_level > self.max_level:
            raise ValueError("min_level > max_level")
        return self


class EnemyAbility(_S):
    code: str = Field(max_length=96, pattern=CODE)
    type: Literal["ACTIVE", "ULTIMATE"] = "ACTIVE"
    target: Literal["self", "enemy_single", "enemy_all", "lowest_hp_ally", "party"] = "enemy_single"
    tags: list[str] = Field(default_factory=list, max_length=8)
    cooldown_s: float = Field(default=0, ge=0, le=600)
    cast_time_s: float = Field(default=0, ge=0, le=30)
    effects: list[dict[str, Any]] = Field(min_length=1, max_length=8)


class EnemyAbilityProfileData(_S):
    abilities: list[EnemyAbility] = Field(default_factory=list, max_length=6)
    rules: list[dict[str, Any]] = Field(default_factory=list, max_length=6)
    effects: list[dict[str, Any]] = Field(default_factory=list, max_length=8)


class DropEntry(_S):
    kind: Literal["gold", "item", "item_pool", "material", "currency", "nothing"]
    ref: str | None = Field(default=None, max_length=96, pattern=CODE)
    tier: int | None = Field(default=None, ge=0, le=10)
    category: str | None = Field(default=None, max_length=32, pattern=CODE)
    rarity: Literal["worn", "common", "fine", "rare", "epic", "legendary", "mythic", "relic"] | None = None
    weight: float = Field(gt=0, le=1_000_000)
    chance_pct: float = Field(default=100, gt=0, le=100)
    min_qty: int = Field(default=1, ge=1, le=100_000)
    max_qty: int = Field(default=1, ge=1, le=100_000)
    boss_only: bool = False
    rare: bool = False  # boosted by risk profile rare_bonus_percent

    @model_validator(mode="after")
    def _shape(self) -> "DropEntry":
        if self.kind in ("item", "material", "currency") and not self.ref:
            raise ValueError(f"{self.kind} entries need ref")
        if self.kind == "item_pool" and self.tier is None:
            raise ValueError("item_pool entries need tier")
        if self.max_qty < self.min_qty:
            raise ValueError("max_qty < min_qty")
        return self


class DropTableData(_S):
    rolls: int = Field(ge=0, le=20)
    entries: list[DropEntry] = Field(min_length=1, max_length=64)


class EnemyData(_S):
    family: str = Field(max_length=32, pattern=CODE)
    archetype: str = Field(max_length=32, pattern=CODE)
    rank: Literal["normal", "elite"] = "normal"
    damage_type: str = Field(default="physical", max_length=16, pattern=CODE)
    stat_mods: dict[str, float] = Field(default_factory=dict)
    ability_profile_code: str | None = Field(default=None, max_length=96)
    effects: list[dict[str, Any]] = Field(default_factory=list, max_length=8)
    tags: list[str] = Field(default_factory=list, max_length=8)
    reward_pct: int = Field(default=100, ge=0, le=1000)

    _mods = field_validator("stat_mods")(_check_mods)


class BossPhase(_S):
    hp_below_pct: float = Field(gt=0, lt=100)
    effects: list[dict[str, Any]] = Field(min_length=1, max_length=5)


class BossAdd(_S):
    enemy_code: str = Field(max_length=96)
    count: int = Field(ge=1, le=4)


class BossData(_S):
    family: str = Field(max_length=32, pattern=CODE)
    archetype: str = Field(max_length=32, pattern=CODE)
    damage_type: str = Field(default="physical", max_length=16, pattern=CODE)
    stat_mods: dict[str, float] = Field(default_factory=dict)
    ability_profile_code: str | None = Field(default=None, max_length=96)
    effects: list[dict[str, Any]] = Field(default_factory=list, max_length=8)
    phases: list[BossPhase] = Field(default_factory=list, max_length=4)
    adds: list[BossAdd] = Field(default_factory=list, max_length=3)
    enrage_after_s: float | None = Field(default=None, gt=10, le=3600)
    drop_table_code: str | None = Field(default=None, max_length=96)
    reward_pct: int = Field(default=1000, ge=0, le=10_000)

    _mods = field_validator("stat_mods")(_check_mods)


class EncounterMember(_S):
    enemy_code: str = Field(max_length=96)
    min: int = Field(ge=1, le=5)
    max: int = Field(ge=1, le=5)

    @model_validator(mode="after")
    def _range(self) -> "EncounterMember":
        if self.max < self.min:
            raise ValueError("max < min")
        return self


class EncounterData(_S):
    members: list[EncounterMember] = Field(max_length=4)
    tags: list[str] = Field(default_factory=list, max_length=8)


class PoolEntry(_S):
    encounter_code: str = Field(max_length=96)
    weight: float = Field(gt=0, le=10_000)


class BossPoolEntry(_S):
    boss_code: str = Field(max_length=96)
    weight: float = Field(gt=0, le=10_000)


class LootModifiers(_S):
    xp_pct: float = Field(default=100, gt=0, le=500)
    gold_pct: float = Field(default=100, gt=0, le=500)
    drop_pct: float = Field(default=100, gt=0, le=500)
    rare_pct: float = Field(default=100, gt=0, le=500)


class ProfessionNode(_S):
    profession_code: str = Field(max_length=32, pattern=CODE)
    node_code: str = Field(max_length=96, pattern=CODE)
    tier: int = Field(ge=0, le=10)
    weight: float = Field(default=1, gt=0, le=1000)


class ZoneRequirement(_S):
    kind: Literal["min_level", "zone_cleared", "class_stage", "quest"]
    value: int | None = Field(default=None, ge=1, le=1000)
    code: str | None = Field(default=None, max_length=96, pattern=CODE)

    @model_validator(mode="after")
    def _shape(self) -> "ZoneRequirement":
        if self.kind == "min_level" and self.value is None:
            raise ValueError("min_level requirement needs value")
        if self.kind in ("zone_cleared", "quest", "class_stage") and not self.code:
            raise ValueError(f"{self.kind} requirement needs code")
        return self


class ZoneData(_S):
    tier_code: str = Field(max_length=96)
    sort_order: int = Field(default=0, ge=0, le=100_000)
    min_level: int = Field(ge=1, le=1000)
    recommended_level: int = Field(ge=1, le=1000)
    max_level: int = Field(ge=1, le=1000)
    danger_rating: int = Field(ge=1, le=10)
    environment_tags: list[str] = Field(default_factory=list, max_length=12)
    encounter_pool: list[PoolEntry] = Field(max_length=16)
    boss_pool: list[BossPoolEntry] = Field(default_factory=list, max_length=8)
    boss_chance_pct: float = Field(default=0, ge=0, le=100)
    loot_modifiers: LootModifiers = Field(default_factory=LootModifiers)
    drop_table_code: str | None = Field(default=None, max_length=96)
    profession_nodes: list[ProfessionNode] = Field(default_factory=list, max_length=16)
    requirements: list[ZoneRequirement] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def _levels(self) -> "ZoneData":
        if not self.min_level <= self.recommended_level <= self.max_level:
            raise ValueError("invalid_level_range: need min_level <= recommended_level <= max_level")
        return self


# --------------------------------------------------------------------------- helpers
async def _status(db: AsyncSession, model: Any, code: str) -> str | None:
    row = (await db.execute(select(model.status, model.deleted_at).where(model.code == code))).first()
    if row is None or row[1] is not None or row[0] == "archived":
        return None
    return str(row[0])


async def _ref(db: AsyncSession, model: Any, code: str | None, path: str) -> list[Issue]:
    if code is None:
        return []
    status = await _status(db, model, code)
    if status is None:
        return [Issue("error", "unknown_reference", f"unknown or archived {model.__tablename__}: {code}", path)]
    if status != "published":
        return [Issue("warning", "reference_unpublished", f"{code} is {status}; publish it together", path)]
    return []


def _effects(effects: list[dict[str, Any]], path: str) -> list[Issue]:
    try:
        validate_effects(effects, path)
    except EffectValidationError as exc:
        return [Issue("error", "invalid_effect", exc.message, exc.path)]
    return []


async def _scaling(db: AsyncSession) -> EnemyScaling:
    return await get_published_balance(db, "enemy_scaling", EnemyScaling)


# --------------------------------------------------------------------------- validators
async def validate_ability_profile(db: AsyncSession, code: str, d: dict[str, Any]) -> list[Issue]:
    issues = _effects(d["effects"], "effects")
    for i, a in enumerate(d["abilities"]):
        issues += _effects(a["effects"], f"abilities[{i}].effects")
    try:
        rules = validate_rules(d["rules"])
    except RuleValidationError as exc:
        return [*issues, Issue("error", "invalid_rule", str(exc), "rules")]
    codes = {a["code"] for a in d["abilities"]}
    tags = {t for a in d["abilities"] for t in a["tags"]}
    for i, r in enumerate(rules.rules):
        if (r.use.ability and r.use.ability not in codes) or (r.use.tag and r.use.tag not in tags):
            issues.append(
                Issue("error", "unknown_reference", "rule uses an ability/tag not in this profile", f"rules[{i}]")
            )
    return issues


async def validate_drop_table(db: AsyncSession, code: str, d: dict[str, Any]) -> list[Issue]:
    issues: list[Issue] = []
    for i, e in enumerate(d["entries"]):
        for check in DROP_REFERENCE_CHECKERS:
            issue = await check(db, e)
            if issue is not None:
                issues.append(Issue(issue.level, issue.code, issue.message, f"entries[{i}]"))
    if all(e["kind"] == "nothing" for e in d["entries"]):
        issues.append(Issue("warning", "empty_drop_table", "drop table can never drop anything", "entries"))
    return issues


def _damage_type(d: dict[str, Any]) -> list[Issue]:
    if d["damage_type"] in DAMAGE_TYPES:
        return []
    return [Issue("error", "invalid_damage_type", f"unknown damage type {d['damage_type']}", "damage_type")]


async def validate_enemy(db: AsyncSession, code: str, d: dict[str, Any]) -> list[Issue]:
    issues = _effects(d["effects"], "effects") + _damage_type(d)
    issues += await _ref(db, EnemyAbilityProfile, d["ability_profile_code"], "ability_profile_code")
    if d["archetype"] not in (await _scaling(db)).archetypes:
        issues.append(Issue("error", "unknown_reference", f"unknown archetype {d['archetype']}", "archetype"))
    return issues


async def validate_boss(db: AsyncSession, code: str, d: dict[str, Any]) -> list[Issue]:
    issues = _effects(d["effects"], "effects") + _damage_type(d)
    for i, p in enumerate(d["phases"]):
        issues += _effects(p["effects"], f"phases[{i}].effects")
    issues += await _ref(db, EnemyAbilityProfile, d["ability_profile_code"], "ability_profile_code")
    issues += await _ref(db, DropTable, d["drop_table_code"], "drop_table_code")
    for i, a in enumerate(d["adds"]):
        issues += await _ref(db, EnemyTemplate, a["enemy_code"], f"adds[{i}].enemy_code")
    if d["archetype"] not in (await _scaling(db)).archetypes:
        issues.append(Issue("error", "unknown_reference", f"unknown archetype {d['archetype']}", "archetype"))
    return issues


async def validate_encounter(db: AsyncSession, code: str, d: dict[str, Any]) -> list[Issue]:
    if not d["members"]:
        return [Issue("error", "empty_encounter", "encounter has no enemies", "members")]
    issues: list[Issue] = []
    for i, m in enumerate(d["members"]):
        issues += await _ref(db, EnemyTemplate, m["enemy_code"], f"members[{i}].enemy_code")
    cfg = await _scaling(db)
    if sum(m["min"] for m in d["members"]) > cfg.max_pack_size:
        issues.append(Issue("error", "pack_too_large", f"minimum pack exceeds {cfg.max_pack_size}", "members"))
    return issues


async def _prereq_graph(db: AsyncSession, code: str, d: dict[str, Any]) -> dict[str, list[str]]:
    rows = (
        await db.execute(
            select(Zone.code, Zone.requirements).where(Zone.deleted_at.is_(None), Zone.status != "archived")
        )
    ).all()
    graph = {c: [r["code"] for r in reqs if r.get("kind") == "zone_cleared"] for c, reqs in rows}
    graph[code] = [r["code"] for r in d["requirements"] if r["kind"] == "zone_cleared"]
    return graph


def _has_cycle(graph: dict[str, list[str]], start: str) -> bool:
    stack, seen = list(graph.get(start, [])), set()
    while stack:
        node = stack.pop()
        if node == start:
            return True
        if node in seen:
            continue
        seen.add(node)
        stack += graph.get(node, [])
    return False


async def validate_zone(db: AsyncSession, code: str, d: dict[str, Any]) -> list[Issue]:
    issues: list[Issue] = []
    tier = (
        await db.execute(select(ZoneTier).where(ZoneTier.code == d["tier_code"], ZoneTier.deleted_at.is_(None)))
    ).scalar_one_or_none()
    if tier is None:
        return [Issue("error", "unknown_reference", "unknown zone tier", "tier_code")]
    if not d["min_level"] <= d["recommended_level"] <= d["max_level"]:
        issues.append(Issue("error", "invalid_level_range", "need min <= recommended <= max", "min_level"))
    elif d["min_level"] > tier.max_level or d["max_level"] < tier.min_level:
        issues.append(
            Issue("error", "invalid_level_range", f"range outside tier {tier.min_level}-{tier.max_level}", "min_level")
        )
    if not d["encounter_pool"]:
        issues.append(Issue("error", "empty_encounter_pool", "zone has no encounters", "encounter_pool"))
    for i, p in enumerate(d["encounter_pool"]):
        issues += await _ref(db, EncounterTemplate, p["encounter_code"], f"encounter_pool[{i}]")
    for i, b in enumerate(d["boss_pool"]):
        issues += await _ref(db, BossTemplate, b["boss_code"], f"boss_pool[{i}]")
    if d["boss_chance_pct"] > 0 and not d["boss_pool"]:
        issues.append(Issue("error", "empty_boss_pool", "boss chance set but boss pool is empty", "boss_pool"))
    issues += await _ref(db, DropTable, d["drop_table_code"], "drop_table_code")
    # prerequisites: circular + unreachable
    if _has_cycle(await _prereq_graph(db, code, d), code):
        issues.append(Issue("error", "circular_prerequisite", "zone prerequisites form a cycle", "requirements"))
    for i, r in enumerate(d["requirements"]):
        if r["kind"] == "min_level" and r["value"] > d["max_level"]:
            issues.append(
                Issue("error", "zone_unreachable", "level requirement above zone max level", f"requirements[{i}]")
            )
        if r["kind"] == "zone_cleared":
            pre = (
                await db.execute(select(Zone).where(Zone.code == r["code"], Zone.deleted_at.is_(None)))
            ).scalar_one_or_none()
            if pre is None or pre.status in ("archived", "disabled"):
                issues.append(
                    Issue(
                        "error", "zone_unreachable", f"prerequisite zone {r['code']} unavailable", f"requirements[{i}]"
                    )
                )
            elif pre.min_level > d["max_level"]:
                issues.append(
                    Issue(
                        "error",
                        "zone_unreachable",
                        f"prerequisite {r['code']} needs Lv{pre.min_level}",
                        f"requirements[{i}]",
                    )
                )
    issues += await _enemy_sanity(db, d, tier)
    return issues


async def _enemy_sanity(db: AsyncSession, d: dict[str, Any], tier: ZoneTier) -> list[Issue]:
    cfg = await _scaling(db)
    ts = TierScaling.model_validate(tier.scaling)
    enc_codes = [p["encounter_code"] for p in d["encounter_pool"]]
    encs = (await db.execute(select(EncounterTemplate).where(EncounterTemplate.code.in_(enc_codes)))).scalars()
    enemy_codes = {m["enemy_code"] for e in encs for m in e.members}
    enemies = list((await db.execute(select(EnemyTemplate).where(EnemyTemplate.code.in_(enemy_codes)))).scalars())
    bosses = list(
        (
            await db.execute(
                select(BossTemplate).where(BossTemplate.code.in_([b["boss_code"] for b in d["boss_pool"]]))
            )
        ).scalars()
    )
    issues: list[Issue] = []
    targets = [(e.code, e.rank, e.archetype, e.stat_mods) for e in enemies]
    targets += [(b.code, "boss", b.archetype, b.stat_mods) for b in bosses]
    for ecode, rank, archetype, mods in sorted(targets):
        for level in sorted({d["min_level"], d["max_level"]}):
            if archetype not in cfg.archetypes:
                continue
            stats = enemy_stats(cfg, ts, level, rank=rank, archetype=archetype, stat_mods=mods)
            for problem in sanity_issues(cfg, stats, level, rank):
                issues.append(
                    Issue("warning", "impossible_enemy_stats", f"{ecode} @Lv{level}: {problem}", "encounter_pool")
                )
    return issues


ZONE_TIER_TYPE = register(ContentType("zone_tier", ZoneTier, ZoneTierData, "zone_tier", public=True))
ENEMY_ABILITY_PROFILE_TYPE = register(
    ContentType(
        "enemy_ability_profile",
        EnemyAbilityProfile,
        EnemyAbilityProfileData,
        "enemy_ability_profile",
        validators=(validate_ability_profile,),
    )
)
DROP_TABLE_TYPE = register(
    ContentType("drop_table", DropTable, DropTableData, "drop_table", validators=(validate_drop_table,))
)
ENEMY_TYPE = register(
    ContentType("enemy", EnemyTemplate, EnemyData, "enemy", validators=(validate_enemy,), public=True)
)
BOSS_TYPE = register(ContentType("boss", BossTemplate, BossData, "boss", validators=(validate_boss,), public=True))
ENCOUNTER_TYPE = register(
    ContentType("encounter", EncounterTemplate, EncounterData, "encounter", validators=(validate_encounter,))
)
ZONE_TYPE = register(
    ContentType(
        "zone", Zone, ZoneData, "zone", validators=(validate_zone,), public=True, searchable_fields=("tier_code",)
    )
)
