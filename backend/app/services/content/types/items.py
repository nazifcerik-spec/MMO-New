"""Item content types (templates, affixes, sets) with publish validators: tier gates, rarity/affix budget,
unique/mastery rules, requirement budget (60/70%), slot/family/stack consistency, references, effects."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.game_engine.effects import EffectValidationError, validate_effects
from app.game_engine.item_generator import ItemStudioConfig
from app.game_engine.items import (
    CATEGORIES,
    EQUIP_SLOTS,
    RARITY_ORDER,
    SLOTS_BY_CATEGORY,
    STACKABLE_CATEGORIES,
    ItemRules,
    requirement_problems,
)
from app.game_engine.stats import ALL_STATS, PRIMARY_STATS
from app.models.classes import ArmorFamily, BaseClass, WeaponFamily
from app.models.items import AffixDefinition, ItemSet, ItemTemplate
from app.models.race import Race
from app.services.content.registry import ContentType, Issue, register
from app.services.content.types.balance import BALANCE_SCHEMAS, get_published_balance

BALANCE_SCHEMAS["item_rules"] = ItemRules
BALANCE_SCHEMAS["item_studio"] = ItemStudioConfig
CODE = r"^[a-z0-9_]+$"
CLASS_TAGS = ("vanguard", "slayer", "shadow", "hunter", "arcane", "faith", "harmony", "primal", "spirit")
Rarity = Literal["worn", "common", "fine", "rare", "epic", "legendary", "mythic", "relic"]


class _S(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SetBonus(_S):
    pieces: int = Field(ge=2, le=8)
    effects: list[dict[str, Any]] = Field(min_length=1, max_length=6)


class ItemSetData(_S):
    bonuses: list[SetBonus] = Field(min_length=1, max_length=4)


class AffixEffect(_S):
    effect_type: Literal["STAT_FLAT", "STAT_PERCENT", "DAMAGE_MULTIPLIER", "DAMAGE_REDUCTION", "HEAL_MULTIPLIER"]
    params: dict[str, Any] = Field(default_factory=dict)
    value_param: Literal["amount", "percent"]


class AffixRollBand(_S):
    tier_from: int = Field(ge=0, le=10)
    tier_to: int = Field(ge=0, le=10)
    min: float = Field(ge=-100_000, le=100_000)
    max: float = Field(ge=-100_000, le=100_000)

    @model_validator(mode="after")
    def _order(self) -> "AffixRollBand":
        if self.tier_to < self.tier_from or self.max < self.min:
            raise ValueError("tier_to >= tier_from and max >= min required")
        return self


class AffixData(_S):
    kind: Literal["prefix", "suffix"]
    group: str = Field(max_length=48, pattern=CODE)
    categories: list[str] = Field(default_factory=list, max_length=9)
    slots: list[str] = Field(default_factory=list, max_length=14)
    class_tag: str | None = None
    tier_min: int = Field(default=0, ge=0, le=10)
    tier_max: int = Field(default=10, ge=0, le=10)
    rarity_min: Rarity = "common"
    weight: int = Field(default=100, ge=1, le=100_000)
    effect: AffixEffect
    rolls: list[AffixRollBand] = Field(min_length=1, max_length=11)

    @model_validator(mode="after")
    def _check(self) -> "AffixData":
        if any(c not in CATEGORIES for c in self.categories) or any(s not in EQUIP_SLOTS for s in self.slots):
            raise ValueError("unknown category or slot")
        if self.class_tag is not None and self.class_tag not in CLASS_TAGS:
            raise ValueError("unknown class tag")
        if self.tier_max < self.tier_min:
            raise ValueError("tier_max < tier_min")
        return self


class StatLine(_S):
    stat: str
    amount: float = Field(ge=-100_000, le=100_000)

    @field_validator("stat")
    @classmethod
    def _stat(cls, v: str) -> str:
        if v not in ALL_STATS:
            raise ValueError(f"unknown stat {v}")
        return v


class Requirements(_S):
    stats: dict[str, int] = Field(default_factory=dict)
    profession: dict[str, Any] | None = None  # {code, level} — validated by profession module (Phase 17)

    @field_validator("stats")
    @classmethod
    def _primary(cls, v: dict[str, int]) -> dict[str, int]:
        for k, n in v.items():
            if k not in PRIMARY_STATS or not 0 <= n <= 5000:
                raise ValueError(f"invalid stat requirement {k}={n}")
        return v


class AffixRules(_S):
    pool: list[str] = Field(default_factory=list, max_length=64)  # affix codes or 'group:<group>'
    min: int | None = Field(default=None, ge=0, le=10)
    max: int | None = Field(default=None, ge=0, le=10)
    fixed: list[dict[str, Any]] = Field(default_factory=list, max_length=6)  # relic: fixed affix effects


class UniqueEffect(_S):
    key: str = Field(max_length=96, pattern=CODE)
    effects: list[dict[str, Any]] = Field(min_length=1, max_length=6)
    mastery_scaling: bool = False


class Socketing(_S):
    min: int = Field(default=0, ge=0, le=6)
    max: int = Field(default=0, ge=0, le=6)


class Durability(_S):
    max: int = Field(default=0, ge=0, le=10_000)


class SalvageOutput(_S):
    template_code: str = Field(max_length=96, pattern=CODE)
    min_qty: int = Field(default=1, ge=1, le=1000)
    max_qty: int = Field(default=1, ge=1, le=1000)
    chance_pct: float = Field(default=100, gt=0, le=100)


class Source(_S):
    kind: Literal["drop", "craft", "vendor", "quest", "event", "starter", "admin"]
    ref: str | None = Field(default=None, max_length=96)


class ItemTemplateData(_S):
    category: Literal[
        "weapon",
        "armor",
        "accessory",
        "profession_tool",
        "consumable",
        "material",
        "recipe",
        "quest_key_token",
        "cosmetic_collectible",
    ]
    subcategory: str | None = Field(default=None, max_length=32, pattern=CODE)
    family: str | None = Field(default=None, max_length=48, pattern=CODE)
    slot: str | None = None
    weapon_family: str | None = Field(default=None, max_length=96)
    armor_family: str | None = Field(default=None, max_length=96)
    tier: int = Field(ge=0, le=10)
    min_level: int = Field(ge=1, le=1000)
    rarity: Rarity
    stack_size: int = Field(default=1, ge=1, le=9999)
    bind_policy: Literal["none", "on_pickup", "on_equip", "account"] = "none"
    tradeable: bool = True
    sellable: bool = True
    vendor_value: int = Field(default=0, ge=0, le=10**12)
    durability: Durability = Field(default_factory=Durability)
    sockets: Socketing = Field(default_factory=Socketing)
    class_tags: list[str] = Field(default_factory=list, max_length=4)
    allowed_classes: list[str] = Field(default_factory=list, max_length=10)
    blocked_classes: list[str] = Field(default_factory=list, max_length=10)
    allowed_races: list[str] = Field(default_factory=list, max_length=8)
    blocked_races: list[str] = Field(default_factory=list, max_length=8)
    requirement_profile: str | None = Field(default=None, max_length=32)
    requirements: Requirements = Field(default_factory=Requirements)
    base_stats: list[StatLine] = Field(default_factory=list, max_length=12)
    effects: list[dict[str, Any]] = Field(default_factory=list, max_length=8)
    affix_rules: AffixRules = Field(default_factory=AffixRules)
    unique_effect: UniqueEffect | None = None
    set_code: str | None = Field(default=None, max_length=96)
    salvage: list[SalvageOutput] = Field(default_factory=list, max_length=8)
    icon: str | None = Field(default=None, max_length=200, pattern=r"^[a-z0-9_/.-]+$")
    sources: list[Source] = Field(default_factory=list, max_length=16)
    short_description_key: str | None = Field(default=None, max_length=200)
    lore_key: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def _shape(self) -> "ItemTemplateData":
        if any(t not in CLASS_TAGS for t in self.class_tags):
            raise ValueError("unknown class tag")
        if self.slot is not None and self.slot not in EQUIP_SLOTS:
            raise ValueError("unknown slot")
        return self


def _effects(effects: list[dict[str, Any]], path: str) -> list[Issue]:
    try:
        validate_effects(effects, path)
    except EffectValidationError as exc:
        return [Issue("error", "invalid_effect", exc.message, exc.path)]
    return []


async def _live(db: AsyncSession, model: Any, code: str) -> bool:
    row = (await db.execute(select(model.status, model.deleted_at).where(model.code == code))).first()
    return row is not None and row[1] is None and row[0] != "archived"


async def item_rules(db: AsyncSession) -> ItemRules:
    return await get_published_balance(db, "item_rules", ItemRules)


async def validate_set(db: AsyncSession, code: str, d: dict[str, Any]) -> list[Issue]:
    issues: list[Issue] = []
    for i, b in enumerate(d["bonuses"]):
        issues += _effects(b["effects"], f"bonuses[{i}].effects")
    if len({b["pieces"] for b in d["bonuses"]}) != len(d["bonuses"]):
        issues.append(Issue("error", "duplicate_set_bonus", "one bonus per piece count", "bonuses"))
    return issues


async def validate_affix(db: AsyncSession, code: str, d: dict[str, Any]) -> list[Issue]:
    e = d["effect"]
    params = {**e["params"], e["value_param"]: max(abs(r["max"]) for r in d["rolls"]) or 1}
    issues = _effects([{"effect_type": e["effect_type"], "params": params}], "effect")
    covered = {t for r in d["rolls"] for t in range(r["tier_from"], r["tier_to"] + 1)}
    missing = [t for t in range(d["tier_min"], d["tier_max"] + 1) if t not in covered]
    if missing:
        issues.append(Issue("error", "affix_roll_gap", f"no roll band for tiers {missing}", "rolls"))
    return issues


async def validate_template(db: AsyncSession, code: str, d: dict[str, Any]) -> list[Issue]:
    rules = await item_rules(db)
    issues: list[Issue] = []
    gate = rules.gate(d["tier"])
    cat, slot = d["category"], d["slot"]
    # tier gate
    if not gate.min_level <= d["min_level"] <= gate.max_level:
        issues.append(
            Issue(
                "error",
                "tier_level_mismatch",
                f"T{d['tier']} items need Lv{gate.min_level}-{gate.max_level}",
                "min_level",
            )
        )
    if d["rarity"] not in gate.rarities and d["rarity"] != "worn":
        issues.append(Issue("warning", "rarity_outside_tier_band", f"T{d['tier']} band is {gate.rarities}", "rarity"))
    # category / slot / family consistency
    allowed_slots = SLOTS_BY_CATEGORY.get(cat)
    if allowed_slots is None and slot is not None:
        issues.append(Issue("error", "slot_not_allowed", f"{cat} items are not equippable", "slot"))
    if allowed_slots is not None and slot not in allowed_slots:
        issues.append(Issue("error", "slot_not_allowed", f"{cat} slot must be one of {allowed_slots}", "slot"))
    if cat == "weapon" and not d["weapon_family"]:
        issues.append(Issue("error", "missing_family", "weapons need a weapon family", "weapon_family"))
    if cat != "weapon" and d["weapon_family"]:
        issues.append(Issue("error", "unexpected_family", "only weapons have a weapon family", "weapon_family"))
    if cat == "armor" and not d["armor_family"] and slot not in ("back",):
        issues.append(Issue("error", "missing_family", "armor needs an armor family", "armor_family"))
    if d["weapon_family"] and not await _live(db, WeaponFamily, d["weapon_family"]):
        issues.append(Issue("error", "unknown_reference", "unknown weapon family", "weapon_family"))
    if d["armor_family"] and not await _live(db, ArmorFamily, d["armor_family"]):
        issues.append(Issue("error", "unknown_reference", "unknown armor family", "armor_family"))
    # stacking
    stackable = cat in STACKABLE_CATEGORIES
    if d["stack_size"] > 1 and not stackable:
        issues.append(Issue("error", "not_stackable", f"{cat} items cannot stack", "stack_size"))
    if d["stack_size"] > 1 and (d["affix_rules"]["pool"] or d["sockets"]["max"] or d["durability"]["max"]):
        issues.append(
            Issue(
                "error", "stack_with_instance_state", "stackables cannot have affixes/sockets/durability", "stack_size"
            )
        )
    # rarity budget / unique / mastery
    budget = rules.rarity_budgets[d["rarity"]]
    ar = d["affix_rules"]
    lo = ar["min"] if ar["min"] is not None else budget.min
    hi = ar["max"] if ar["max"] is not None else budget.max
    if cat in SLOTS_BY_CATEGORY and (lo < budget.min or hi > budget.max or lo > hi):
        issues.append(
            Issue("error", "affix_budget", f"{d['rarity']} allows {budget.min}-{budget.max} affixes", "affix_rules")
        )
    if budget.fixed and ar["pool"]:
        issues.append(
            Issue("error", "relic_random_affixes", "relics use fixed effects, not random affixes", "affix_rules")
        )
    if budget.unique_required and not d["unique_effect"]:
        issues.append(Issue("error", "unique_required", f"{d['rarity']} items need a unique effect", "unique_effect"))
    if budget.mastery_scaling_required and not (d["unique_effect"] or {}).get("mastery_scaling"):
        issues.append(
            Issue("error", "mastery_scaling_required", "mythic unique effects must scale with mastery", "unique_effect")
        )
    if RARITY_ORDER.index(d["rarity"]) < RARITY_ORDER.index("legendary") and d["unique_effect"]:
        issues.append(
            Issue("warning", "unexpected_unique", "unique effects are reserved for legendary+", "unique_effect")
        )
    equippable = cat in SLOTS_BY_CATEGORY
    if not equippable and (ar["pool"] or ar["fixed"]):
        issues.append(Issue("error", "affixes_not_allowed", f"{cat} items cannot have affixes", "affix_rules"))
    elif equippable and not ar["pool"] and not budget.fixed:
        if lo > 0:
            issues.append(Issue("error", "empty_affix_pool", "item must roll affixes but has no pool", "affix_rules"))
        elif hi > 0:
            issues.append(
                Issue("warning", "empty_affix_pool", "item could roll affixes but has no pool", "affix_rules")
            )
    for i, entry in enumerate(ar["pool"]):
        if entry.startswith("group:"):
            grp = entry.removeprefix("group:")
            found = (await db.execute(select(AffixDefinition.id).where(AffixDefinition.group == grp))).first()
            if found is None:
                issues.append(
                    Issue("error", "unknown_reference", f"no affixes in group {grp}", f"affix_rules.pool[{i}]")
                )
        elif not await _live(db, AffixDefinition, entry):
            issues.append(Issue("error", "unknown_reference", f"unknown affix {entry}", f"affix_rules.pool[{i}]"))
    # sockets / durability
    if d["sockets"]["max"] > rules.max_sockets or d["sockets"]["min"] > d["sockets"]["max"]:
        issues.append(Issue("error", "invalid_sockets", f"sockets must be 0-{rules.max_sockets}, min<=max", "sockets"))
    if cat in ("weapon", "armor") and not d["durability"]["max"]:
        issues.append(Issue("warning", "no_durability", "equipment usually has durability", "durability"))
    # requirements
    reqs = d["requirements"]["stats"]
    if d["requirement_profile"] and d["requirement_profile"] not in rules.requirement_profiles:
        issues.append(Issue("error", "unknown_reference", "unknown requirement profile", "requirement_profile"))
    for level, msg in requirement_problems(rules, d["min_level"], reqs):
        issues.append(Issue(level, "requirement_budget", msg, "requirements.stats"))  # type: ignore[arg-type]
    total = sum(reqs.values())
    if reqs and not gate.stat_req_min <= total <= gate.stat_req_max:
        issues.append(
            Issue(
                "warning",
                "requirement_outside_tier_band",
                f"total {total} outside T{d['tier']} suggestion {gate.stat_req_min}-{gate.stat_req_max}",
                "requirements.stats",
            )
        )
    # references
    for field, model in (
        ("allowed_classes", BaseClass),
        ("blocked_classes", BaseClass),
        ("allowed_races", Race),
        ("blocked_races", Race),
    ):
        for c in d[field]:
            if not await _live(db, model, c):
                issues.append(Issue("error", "unknown_reference", f"unknown {field} entry {c}", field))
    if d["set_code"] and not await _live(db, ItemSet, d["set_code"]):
        issues.append(Issue("error", "unknown_reference", "unknown item set", "set_code"))
    for i, s in enumerate(d["salvage"]):
        if s["template_code"] == code or not await _live(db, ItemTemplate, s["template_code"]):
            issues.append(Issue("error", "unknown_reference", "unknown or self salvage output", f"salvage[{i}]"))
    # effects
    issues += _effects(d["effects"], "effects")
    if d["unique_effect"]:
        issues += _effects(d["unique_effect"]["effects"], "unique_effect.effects")
    for i, f in enumerate(ar["fixed"]):
        issues += _effects([f], f"affix_rules.fixed[{i}]")
    return issues


ITEM_SET_TYPE = register(
    ContentType("item_set", ItemSet, ItemSetData, "item_set", validators=(validate_set,), public=True)
)
AFFIX_TYPE = register(
    ContentType(
        "affix",
        AffixDefinition,
        AffixData,
        "affix",
        edit_permission="item.edit",
        publish_permission="item.publish",
        validators=(validate_affix,),
        public=True,
    )
)
ITEM_TEMPLATE_TYPE = register(
    ContentType(
        "item_template",
        ItemTemplate,
        ItemTemplateData,
        "item",
        edit_permission="item.edit",
        publish_permission="item.publish",
        validators=(validate_template,),
        public=True,
        searchable_fields=("category", "family", "rarity"),
    )
)
