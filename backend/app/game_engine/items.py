"""Pure item rules: tier gates, rarity affix budgets, requirement profiles/validation, deterministic rolls and
instance effect assembly (ADR-0004). Instances are always evaluated against their recorded template revision."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.game_engine.rng import Rng, derive_seed
from app.game_engine.stats import PRIMARY_STATS

Rarity = Literal["worn", "common", "fine", "rare", "epic", "legendary", "mythic", "relic"]
RARITY_ORDER: tuple[str, ...] = ("worn", "common", "fine", "rare", "epic", "legendary", "mythic", "relic")
CATEGORIES = (
    "weapon",
    "armor",
    "accessory",
    "profession_tool",
    "consumable",
    "material",
    "recipe",
    "quest_key_token",
    "cosmetic_collectible",
)
STACKABLE_CATEGORIES = ("consumable", "material", "recipe", "quest_key_token")
EQUIP_SLOTS = (
    "main_hand",
    "off_hand",
    "head",
    "shoulders",
    "chest",
    "hands",
    "waist",
    "legs",
    "feet",
    "back",
    "neck",
    "ring",
    "trinket",
    "tool",
)
SLOTS_BY_CATEGORY: dict[str, tuple[str, ...]] = {
    "weapon": ("main_hand", "off_hand"),
    "armor": ("head", "shoulders", "chest", "hands", "waist", "legs", "feet", "back", "off_hand"),
    "accessory": ("neck", "ring", "trinket"),
    "profession_tool": ("tool",),
}


class _S(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class TierGate(_S):
    tier: int = Field(ge=0, le=10)
    min_level: int = Field(ge=1, le=1000)
    max_level: int = Field(ge=1, le=1000)
    rarities: tuple[Rarity, ...] = Field(min_length=1)
    stat_req_min: int = Field(ge=0)
    stat_req_max: int = Field(ge=0)


class AffixBudget(_S):
    min: int = Field(ge=0, le=10)
    max: int = Field(ge=0, le=10)
    unique_required: bool = False
    mastery_scaling_required: bool = False
    fixed: bool = False  # relic: fixed, build-changing, never random


class RequirementProfile(_S):
    """Canonical Lv600 example (primary + secondary); scaled linearly by level for suggestions."""

    primary: tuple[str, ...] = Field(min_length=1)  # alternatives are allowed, e.g. INT|WIS
    secondary: str
    primary_at_600: int = Field(ge=0)
    secondary_at_600: int = Field(ge=0)


class ItemRules(_S):
    tiers: tuple[TierGate, ...] = Field(min_length=11, max_length=11)
    rarity_budgets: dict[Rarity, AffixBudget]
    requirement_profiles: dict[str, RequirementProfile]
    base_stat_value: int = Field(ge=0)  # every primary stat starts here
    points_per_level: int = Field(ge=1)
    requirement_warn_pct: float = Field(gt=0, le=100)  # of distributable budget at the item's min level
    requirement_error_pct: float = Field(gt=0, le=100)
    max_sockets: int = Field(ge=0, le=6)
    max_upgrade_level: int = Field(ge=0, le=30)
    upgrade_pct_per_level: float = Field(ge=0, le=50)

    @model_validator(mode="after")
    def _check(self) -> "ItemRules":
        if [t.tier for t in self.tiers] != list(range(11)):
            raise ValueError("tiers must be T0..T10 in order")
        if set(self.rarity_budgets) != set(RARITY_ORDER):
            raise ValueError("rarity budgets must cover every rarity")
        if self.requirement_warn_pct > self.requirement_error_pct:
            raise ValueError("warn threshold above error threshold")
        return self

    def gate(self, tier: int) -> TierGate:
        return self.tiers[tier]


def distributable_budget(rules: ItemRules, level: int) -> int:
    """Total primary stats a character can have at `level` from base + allocated points (no gear/effects)."""
    return rules.base_stat_value * len(PRIMARY_STATS) + (level - 1) * rules.points_per_level


def suggested_requirements(rules: ItemRules, profile: str, level: int, tier: int | None = None) -> dict[str, int]:
    """Profile requirement scaled linearly from its Lv600 example; clamped to the tier's suggested total band."""
    p = rules.requirement_profiles[profile]
    scale = level / 600
    if tier is not None:
        gate = rules.gate(tier)
        total = (p.primary_at_600 + p.secondary_at_600) * scale
        if total > gate.stat_req_max:
            scale *= gate.stat_req_max / total
    return {p.primary[0]: int(p.primary_at_600 * scale), p.secondary: int(p.secondary_at_600 * scale)}


def requirement_problems(rules: ItemRules, min_level: int, reqs: dict[str, int]) -> list[tuple[str, str]]:
    """(level, message) where level is 'warning' or 'error'."""
    budget = distributable_budget(rules, min_level)
    total = sum(reqs.values())
    out: list[tuple[str, str]] = []
    pct = 100 * total / budget
    single = max(reqs.values(), default=0)
    # one stat can absorb at most base + all points
    single_cap = rules.base_stat_value + (min_level - 1) * rules.points_per_level
    if single > single_cap:
        out.append(("error", f"single stat requirement {single} exceeds reachable {single_cap} at Lv{min_level}"))
    if pct > rules.requirement_error_pct:
        out.append(("error", f"requirements use {pct:.0f}% of the Lv{min_level} stat budget ({budget})"))
    elif pct > rules.requirement_warn_pct:
        out.append(("warning", f"requirements use {pct:.0f}% of the Lv{min_level} stat budget ({budget})"))
    return out


# --------------------------------------------------------------------------- rolls
class AffixRoll(_S):
    tier_from: int = Field(ge=0, le=10)
    tier_to: int = Field(ge=0, le=10)
    min: float
    max: float


def affix_count(rules: ItemRules, rarity: str, rng: Rng, override: tuple[int, int] | None = None) -> int:
    b = rules.rarity_budgets[rarity]  # type: ignore[index]
    lo, hi = override or (b.min, b.max)
    lo, hi = max(lo, b.min), min(hi, b.max)
    return rng.randint(lo, hi) if hi >= lo else 0


def _value(rolls: list[dict[str, Any]], tier: int, rng: Rng) -> float | None:
    for r in rolls:
        if r["tier_from"] <= tier <= r["tier_to"]:
            v = rng.uniform(float(r["min"]), float(r["max"]))
            return round(v, 2) if abs(r["max"]) < 20 else float(round(v))
    return None


def roll_affixes(
    rules: ItemRules,
    *,
    tier: int,
    rarity: str,
    category: str,
    slot: str | None,
    pool: list[dict[str, Any]],
    count_override: tuple[int, int] | None,
    seed: int,
) -> list[dict[str, Any]]:
    """Deterministic affix roll: weighted pick without repeating exclusive groups; values from the tier band."""
    if rules.rarity_budgets[rarity].fixed:  # type: ignore[index]
        return []
    rng = Rng(derive_seed(seed, "affixes"))
    n = affix_count(rules, rarity, rng, count_override)
    eligible = [
        a
        for a in pool
        if (not a["categories"] or category in a["categories"])
        and (not a["slots"] or slot in a["slots"])
        and a["tier_min"] <= tier <= a["tier_max"]
        and RARITY_ORDER.index(rarity) >= RARITY_ORDER.index(a["rarity_min"])
    ]
    eligible.sort(key=lambda a: a["code"])
    out: list[dict[str, Any]] = []
    used_groups: set[str] = set()
    class_tag_affixes = 0
    for _ in range(n):
        choices = [
            a for a in eligible if a["group"] not in used_groups and not (a.get("class_tag") and class_tag_affixes >= 1)
        ]
        if not choices:
            break
        pick = choices[rng.weighted_index([float(a["weight"]) for a in choices])]
        value = _value(pick["rolls"], tier, rng)
        if value is None:
            continue
        used_groups.add(pick["group"])
        class_tag_affixes += bool(pick.get("class_tag"))
        effect = {"effect_type": pick["effect"]["effect_type"], "params": {**pick["effect"]["params"]}}
        effect["params"][pick["effect"]["value_param"]] = value
        out.append({"code": pick["code"], "kind": pick["kind"], "value": value, "effect": effect})
    return out


def roll_sockets(socket_cfg: dict[str, Any], seed: int) -> int:
    lo, hi = int(socket_cfg.get("min", 0)), int(socket_cfg.get("max", 0))
    return Rng(derive_seed(seed, "sockets")).randint(lo, hi) if hi > lo else lo


def _scale_effect(effect: dict[str, Any], mult: float) -> dict[str, Any]:
    params = dict(effect["params"])
    for key in ("amount", "percent"):
        if isinstance(params.get(key), int | float):
            params[key] = round(params[key] * mult, 4)
    return {**effect, "params": params}


def instance_effects(template: dict[str, Any], instance: dict[str, Any], rules: ItemRules) -> list[dict[str, Any]]:
    """All effects granted by an equipped instance, computed from the *recorded* template revision data."""
    mult = 1 + instance.get("upgrade_level", 0) * rules.upgrade_pct_per_level / 100
    out = [
        _scale_effect({"effect_type": "STAT_FLAT", "params": {"stat": s["stat"], "amount": s["amount"]}}, mult)
        for s in template.get("base_stats", [])
    ]
    out += list(template.get("effects", []))
    out += [a["effect"] for a in instance.get("affixes", [])]
    unique = template.get("unique_effect")
    if unique:
        out += list(unique["effects"])
    for gem in instance.get("gems", []):
        out += list(gem.get("effects", []))
    return out


def requirement_check(
    template: dict[str, Any], *, level: int, stats: dict[str, float], class_code: str, race_code: str
) -> list[dict[str, Any]]:
    """Unmet requirements (empty = equippable). Stats are the character's primary stat finals."""
    unmet: list[dict[str, Any]] = []
    if level < template["min_level"]:
        unmet.append({"kind": "level", "required": template["min_level"], "have": level})
    for stat, need in template.get("requirements", {}).get("stats", {}).items():
        have = stats.get(stat, 0)
        if have < need:
            unmet.append({"kind": "stat", "stat": stat, "required": need, "have": round(have)})
    allowed, blocked = template.get("allowed_classes") or [], template.get("blocked_classes") or []
    if (allowed and class_code not in allowed) or class_code in blocked:
        unmet.append({"kind": "class", "code": class_code})
    allowed_r, blocked_r = template.get("allowed_races") or [], template.get("blocked_races") or []
    if (allowed_r and race_code not in allowed_r) or race_code in blocked_r:
        unmet.append({"kind": "race", "code": race_code})
    return unmet
