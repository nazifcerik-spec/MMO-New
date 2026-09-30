"""Safe effect registry / DSL (ADR-0005).

Content stores effects as `{"effect_type": str, "schema_version": int, "params": {...}}`. Every
(type, version) maps to a strict Pydantic params model. Nothing in content is ever executed: engines
dispatch on `effect_type` through dict lookups. Unknown types/versions/keys are rejected."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.game_engine.stats import ALL_STATS, DAMAGE_TYPES

Percent = Annotated[float, Field(ge=-100.0, le=1000.0)]
PositivePercent = Annotated[float, Field(gt=0.0, le=100.0)]
Seconds = Annotated[float, Field(gt=0.0, le=3600.0)]
MAX_NESTING = 3


Trigger = Literal[
    "on_hit",
    "on_crit",
    "on_block",
    "on_dodge",
    "on_heal",
    "on_crit_heal",
    "on_kill",
    "on_damage_taken",
    "combat_start",
    "on_resource_spent",
    "on_ability_cast",
]


class StrictParams(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# ---------------------------------------------------------------- conditions (shared with triggers/tactics)
ConditionMetric = Literal[
    "self_hp_pct",
    "self_resource_pct",
    "target_hp_pct",
    "enemy_count",
    "target_debuff_count",
    "self_buff_count",
    "combo_count",
    "stack_count",
    "hit_index",
    "combat_time_s",
    "active_hot_count",
    "missing_hp_pct",
    "party_size",
]
Comparator = Literal["lt", "lte", "gt", "gte", "eq"]


class Condition(StrictParams):
    metric: ConditionMetric
    op: Comparator
    value: float = Field(ge=0, le=100_000)
    stack_code: str | None = Field(default=None, max_length=64, pattern=r"^[a-z0-9_]+$")

    def check(self, observed: float) -> bool:
        return _COMPARATORS[self.op](observed, self.value)


_COMPARATORS: dict[str, Callable[[float, float], bool]] = {
    "lt": lambda a, b: a < b,
    "lte": lambda a, b: a <= b,
    "gt": lambda a, b: a > b,
    "gte": lambda a, b: a >= b,
    "eq": lambda a, b: a == b,
}


# ---------------------------------------------------------------- params models
def _stat(v: str) -> str:
    if v not in ALL_STATS:
        raise ValueError(f"unknown stat '{v}'")
    return v


def _damage_type(v: str | None) -> str | None:
    if v is not None and v not in DAMAGE_TYPES:
        raise ValueError(f"unknown damage type '{v}'")
    return v


class StatFlat(StrictParams):
    stat: str
    amount: float = Field(ge=-100_000, le=100_000)
    _v = field_validator("stat")(_stat)


class StatPercent(StrictParams):
    stat: str
    percent: Percent
    _v = field_validator("stat")(_stat)


class DamageMultiplier(StrictParams):
    percent: Percent
    damage_type: str | None = None
    condition: Condition | None = None
    target_tag: str | None = Field(default=None, max_length=32)  # e.g. boss, elite
    _v = field_validator("damage_type")(_damage_type)


class DamageReduction(StrictParams):
    percent: Annotated[float, Field(gt=0, le=90)]
    duration_s: Seconds | None = None
    max_stacks: int = Field(default=1, ge=1, le=20)
    condition: Condition | None = None


class HealMultiplier(StrictParams):
    percent: Percent
    scope: Literal["outgoing", "received", "hot", "self"] = "outgoing"
    condition: Condition | None = None


class Shield(StrictParams):
    percent_max_hp: Annotated[float, Field(ge=0, le=100)] = 0
    flat: float = Field(default=0, ge=0, le=1_000_000)
    duration_s: Seconds = 6.0
    target: Literal["self", "lowest_hp_ally", "party"] = "self"


class ResourceGain(StrictParams):
    resource: str = Field(max_length=32, pattern=r"^[a-z0-9_]+$")
    amount: float = Field(gt=0, le=1000)


class DamageInstance(StrictParams):
    percent_of_power: Annotated[float, Field(gt=0, le=2000)]
    damage_type: str = "physical"
    guaranteed_crit: bool = False
    armor_ignore_percent: Annotated[float, Field(ge=0, le=100)] = 0
    _v = field_validator("damage_type")(_damage_type)


class Heal(StrictParams):
    percent_of_power: Annotated[float, Field(gt=0, le=2000)]
    target: Literal["self", "lowest_hp_ally", "party"] = "self"


class ProcChance(StrictParams):
    chance_percent: PositivePercent
    trigger: Trigger = "on_hit"
    effects: list["Effect"] = Field(min_length=1, max_length=5)
    internal_cooldown_s: float = Field(default=0, ge=0, le=600)


class ThresholdTrigger(StrictParams):
    condition: Condition
    effects: list["Effect"] = Field(min_length=1, max_length=5)
    once_per_combat: bool = False


class EveryNHits(StrictParams):
    n: int = Field(ge=2, le=100)
    effects: list["Effect"] = Field(min_length=1, max_length=5)


class Dot(StrictParams):
    damage_type: str = "physical"
    percent_of_power: Annotated[float, Field(gt=0, le=500)]
    duration_s: Seconds
    tick_s: Annotated[float, Field(gt=0, le=30)] = 1.0
    max_stacks: int = Field(default=1, ge=1, le=50)
    _v = field_validator("damage_type")(_damage_type)


class Hot(StrictParams):
    percent_of_power: Annotated[float, Field(gt=0, le=500)]
    duration_s: Seconds
    tick_s: Annotated[float, Field(gt=0, le=30)] = 1.0
    max_stacks: int = Field(default=1, ge=1, le=10)
    target: Literal["self", "lowest_hp_ally", "party"] = "self"


class Aura(StrictParams):
    scope: Literal["self", "party"] = "party"
    effects: list["Effect"] = Field(min_length=1, max_length=5)


class Debuff(StrictParams):
    kind: Literal["stat", "slow", "vulnerability", "weaken", "root", "silence", "freeze", "mark"]
    stat: str | None = None
    percent: Percent = 0
    duration_s: Seconds
    max_stacks: int = Field(default=1, ge=1, le=20)
    _v = field_validator("stat")(lambda v: None if v is None else _stat(v))


class CooldownMod(StrictParams):
    percent: Annotated[float, Field(ge=-90, le=90)]
    ability_tag: str | None = Field(default=None, max_length=32)
    chance_no_cooldown_percent: Annotated[float, Field(ge=0, le=50)] = 0


class LootModifier(StrictParams):
    scope: Literal["xp", "gold", "drop_rate", "rare_chance", "material_yield"]
    percent: Percent


class ProgressionModifier(StrictParams):
    kind: Literal["death_penalty", "respec_cost", "consumable_use", "durability_loss", "rested_xp"]
    percent: Percent
    limit_points: int | None = Field(default=None, ge=1, le=3000)  # e.g. Human respec discount on first 300 pts


class ProfessionYieldMod(StrictParams):
    profession: str = Field(max_length=32, pattern=r"^(\*|[a-z_]+)$")
    kind: Literal["yield", "speed", "quality", "rare_find", "xp"]
    percent: Percent


class StackGain(StrictParams):
    stack_code: str = Field(max_length=64, pattern=r"^[a-z0-9_]+$")
    amount: int = Field(default=1, ge=1, le=10)
    max_stacks: int = Field(default=5, ge=1, le=100)
    per_stack: list["Effect"] = Field(default_factory=list, max_length=5)


class Buff(StrictParams):
    """Timed wrapper: apply nested (usually stat) effects for a duration, optionally stacking."""

    duration_s: Seconds
    max_stacks: int = Field(default=1, ge=1, le=20)
    target: Literal["self", "lowest_hp_ally", "party", "target"] = "self"
    effects: list["Effect"] = Field(min_length=1, max_length=5)


class ScalingBonus(StrictParams):
    """+percent_per_step for every `step` of a metric (e.g. +3% damage per 10% missing HP), capped."""

    metric: ConditionMetric
    step: float = Field(gt=0, le=100)
    percent_per_step: float = Field(gt=0, le=100)
    max_percent: float = Field(gt=0, le=500)
    applies_to: Literal["damage", "healing", "buff_power", "damage_reduction", "attack_speed"] = "damage"
    stack_code: str | None = Field(default=None, max_length=64, pattern=r"^[a-z0-9_]+$")


class WeaponFamilyBonus(StrictParams):
    families: list[str] = Field(min_length=1, max_length=30)
    effects: list["Effect"] = Field(min_length=1, max_length=5)


class ResourceCostMod(StrictParams):
    resource: str = Field(max_length=32, pattern=r"^[a-z0-9_]+$")
    percent: Annotated[float, Field(ge=-90, le=200)]


class StackCapMod(StrictParams):
    stack_code: str = Field(max_length=64, pattern=r"^[a-z0-9_]+$")
    amount: int = Field(ge=-10, le=20)


class SoloAccord(StrictParams):
    """Support solo conversion: outside a party, part of support power converts to offensive power."""

    conversion_percent: Annotated[float, Field(ge=0, le=100)]
    source_stats: list[str] = Field(min_length=1, max_length=8)
    target_stats: list[str] = Field(min_length=1, max_length=4)

    @field_validator("source_stats", "target_stats")
    @classmethod
    def _stats(cls, v: list[str]) -> list[str]:
        for s in v:
            _stat(s)
        return v


class Effect(StrictParams):
    effect_type: str = Field(max_length=40)
    schema_version: int = Field(default=1, ge=1)
    params: dict[str, Any]


@dataclass(frozen=True, slots=True)
class EffectType:
    code: str
    version: int
    params_model: type[StrictParams]
    category: Literal["stat", "combat", "trigger", "economy", "profession"]
    description: str


REGISTRY: dict[tuple[str, int], EffectType] = {}


def register(code: str, version: int, model: type[StrictParams], category: Any, description: str) -> None:
    REGISTRY[(code, version)] = EffectType(code, version, model, category, description)


_BUILTINS: list[tuple[str, type[StrictParams], str, str]] = [
    ("STAT_FLAT", StatFlat, "stat", "Add a flat amount to a stat"),
    ("STAT_PERCENT", StatPercent, "stat", "Increase a stat by a percentage"),
    ("DAMAGE_MULTIPLIER", DamageMultiplier, "combat", "Conditional damage bonus"),
    ("DAMAGE_REDUCTION", DamageReduction, "combat", "Damage reduction, optionally stacking/timed"),
    ("HEAL_MULTIPLIER", HealMultiplier, "combat", "Healing done/received bonus"),
    ("SHIELD", Shield, "combat", "Absorb shield"),
    ("RESOURCE_GAIN", ResourceGain, "combat", "Gain class resource"),
    ("DAMAGE", DamageInstance, "combat", "Deal an instance of damage"),
    ("HEAL", Heal, "combat", "Heal an instance"),
    ("PROC_CHANCE", ProcChance, "trigger", "Chance on event to apply nested effects"),
    ("THRESHOLD_TRIGGER", ThresholdTrigger, "trigger", "Apply nested effects while/when a condition holds"),
    ("EVERY_N_HITS", EveryNHits, "trigger", "Apply nested effects every N hits"),
    ("DOT", Dot, "combat", "Damage over time"),
    ("HOT", Hot, "combat", "Heal over time"),
    ("AURA", Aura, "trigger", "Persistent effects on self or party"),
    ("DEBUFF", Debuff, "combat", "Apply a debuff to the target"),
    ("COOLDOWN_MOD", CooldownMod, "combat", "Cooldown recovery modifier"),
    ("LOOT_MODIFIER", LootModifier, "economy", "XP/gold/drop modifiers"),
    ("PROGRESSION_MODIFIER", ProgressionModifier, "economy", "Death penalty, respec cost, consumable use"),
    ("PROFESSION_YIELD_MOD", ProfessionYieldMod, "profession", "Profession yield/speed/quality modifiers"),
    ("STACK_GAIN", StackGain, "trigger", "Gain a named stack with per-stack effects"),
    ("BUFF", Buff, "trigger", "Timed (stacking) buff wrapping nested effects"),
    ("SCALING_BONUS", ScalingBonus, "combat", "Bonus that scales with a combat metric"),
    ("WEAPON_FAMILY_BONUS", WeaponFamilyBonus, "combat", "Effects active with specific weapon families"),
    ("RESOURCE_COST_MOD", ResourceCostMod, "combat", "Resource cost modifier"),
    ("STACK_CAP_MOD", StackCapMod, "combat", "Change the cap of a named stack"),
    ("SOLO_ACCORD", SoloAccord, "combat", "Support solo conversion outside a party"),
]
for _code, _model, _cat, _desc in _BUILTINS:
    register(_code, 1, _model, _cat, _desc)

NESTED_KEYS = ("effects", "per_stack")


class EffectValidationError(ValueError):
    def __init__(self, path: str, message: str) -> None:
        super().__init__(f"{path}: {message}")
        self.path = path
        self.message = message


def validate_effect(raw: Any, path: str = "effect", depth: int = 0) -> StrictParams:
    """Validate one effect dict, recursively validating nested effect lists. Returns the params model."""
    if depth > MAX_NESTING:
        raise EffectValidationError(path, f"nesting deeper than {MAX_NESTING}")
    try:
        env = Effect.model_validate(raw)
    except ValidationError as exc:
        raise EffectValidationError(path, exc.errors()[0]["msg"]) from exc
    et = REGISTRY.get((env.effect_type, env.schema_version))
    if et is None:
        raise EffectValidationError(path, f"unknown effect_type/schema_version {env.effect_type}@{env.schema_version}")
    try:
        params = et.params_model.model_validate(env.params)
    except ValidationError as exc:
        err = exc.errors()[0]
        loc = ".".join(str(p) for p in err["loc"])
        raise EffectValidationError(f"{path}.params.{loc}", err["msg"]) from exc
    for key in NESTED_KEYS:
        for i, nested in enumerate(getattr(params, key, None) or []):
            validate_effect(
                nested.model_dump() if isinstance(nested, BaseModel) else nested, f"{path}.params.{key}[{i}]", depth + 1
            )
    return params


def validate_effects(raw: Any, path: str = "effects") -> list[StrictParams]:
    if not isinstance(raw, list):
        raise EffectValidationError(path, "must be a list")
    if len(raw) > 32:
        raise EffectValidationError(path, "too many effects (max 32)")
    return [validate_effect(e, f"{path}[{i}]") for i, e in enumerate(raw)]


def registry_schema() -> list[dict[str, Any]]:
    """JSON schemas for admin form generation."""
    return [
        {
            "effect_type": et.code,
            "schema_version": et.version,
            "category": et.category,
            "description": et.description,
            "params_schema": et.params_model.model_json_schema(),
        }
        for et in sorted(REGISTRY.values(), key=lambda e: (e.category, e.code))
    ]


for _m in (ProcChance, ThresholdTrigger, EveryNHits, Aura, StackGain, Buff, WeaponFamilyBonus):
    _m.model_rebuild()
