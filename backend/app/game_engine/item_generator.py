"""Pure, deterministic Item Generator Wizard logic: expands wizard parameters into draft template data +
localized names. Nothing here touches the DB; the service validates, dedupes and commits atomically."""

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.game_engine.items import RARITY_ORDER, ItemRules, suggested_requirements

LOCALES = ("en", "tr", "zh-CN", "es")
CODE_RE = re.compile(r"^[a-z][a-z0-9_]{1,95}$")
CODE_PLACEHOLDERS = {"theme", "family", "slot", "tier", "rarity", "n"}
NAME_PLACEHOLDERS = {"theme", "family", "tier", "rarity", "n"}


class _S(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CurvePoint(_S):
    stat: str
    base: float
    per_level: float


class VendorFormula(_S):
    base: float = Field(ge=0)
    per_level: float = Field(ge=0)
    rarity_pow: float = Field(ge=1, le=5)


class DurabilityFormula(_S):
    base: int = Field(ge=0)
    per_tier: int = Field(ge=0)


class GeneratorConfig(_S):
    max_batch: int = Field(ge=1, le=1000)
    curves: dict[str, tuple[CurvePoint, ...]]
    slot_multipliers: dict[str, float]
    rarity_multipliers: dict[str, float]
    vendor_value: VendorFormula
    durability: DurabilityFormula


class PreviewProfile(_S):
    code: str
    class_: str = Field(alias="class")
    race: str
    level: int = Field(ge=1, le=1000)
    stat_profile: str

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


class ItemStudioConfig(_S):
    preview_profiles: tuple[PreviewProfile, ...] = Field(min_length=1)
    generator: GeneratorConfig


class Theme(_S):
    code: str = Field(pattern=r"^[a-z][a-z0-9_]{0,31}$")
    names: dict[str, str]  # locale -> theme word


class GeneratorParams(_S):
    category: Literal["weapon", "armor", "accessory"]
    slot: str
    weapon_family: str | None = None
    armor_family: str | None = None
    tier_from: int = Field(ge=0, le=10)
    tier_to: int = Field(ge=0, le=10)
    rarity_weights: dict[str, int] = Field(min_length=1)
    requirement_profile: str | None = None
    count: int = Field(ge=1, le=1000)
    code_pattern: str = Field(max_length=120)
    name_patterns: dict[str, str]
    theme: Theme
    affix_pool: tuple[str, ...] = ()
    class_tags: tuple[str, ...] = ()
    salvage_material: str | None = None
    unique_effect: dict[str, Any] | None = None  # applied to legendary+ (mastery_scaling forced for mythic)

    @model_validator(mode="after")
    def _check(self) -> "GeneratorParams":
        if self.tier_to < self.tier_from:
            raise ValueError("tier_to < tier_from")
        if any(r not in RARITY_ORDER or w < 0 for r, w in self.rarity_weights.items()) or not sum(
            self.rarity_weights.values()
        ):
            raise ValueError("rarity_weights must use known rarities with a positive total")
        if "en" not in self.name_patterns or any(loc not in LOCALES for loc in self.name_patterns):
            raise ValueError("name_patterns need 'en' and only en/tr/zh-CN/es")
        for field, allowed in (("code_pattern", CODE_PLACEHOLDERS),):
            used = set(re.findall(r"{(\w+)}", getattr(self, field)))
            if not used <= allowed or "n" not in used:
                raise ValueError(f"{field} placeholders must be within {sorted(allowed)} and include {{n}}")
        for loc, pat in self.name_patterns.items():
            if not set(re.findall(r"{(\w+)}", pat)) <= NAME_PLACEHOLDERS:
                raise ValueError(f"name_patterns.{loc} placeholders must be within {sorted(NAME_PLACEHOLDERS)}")
        return self


def allocate(weights: dict[str, int], count: int) -> list[str]:
    """Largest-remainder allocation of `count` over weights, emitted in rarity order (deterministic)."""
    total = sum(weights.values())
    raw = {r: count * w / total for r, w in weights.items()}
    alloc = {r: int(v) for r, v in raw.items()}
    for r in sorted(raw, key=lambda r: (-(raw[r] - alloc[r]), RARITY_ORDER.index(r)))[: count - sum(alloc.values())]:
        alloc[r] += 1
    return [r for r in RARITY_ORDER for _ in range(alloc.get(r, 0))]


def curve_key(category: str, weapon_kind: str | None, armor_family: str | None) -> str:
    if category == "weapon":
        return f"weapon_{weapon_kind or 'melee'}"
    if category == "armor":
        return f"armor_{armor_family or 'cloth'}"
    return "accessory"


def generate(
    params: GeneratorParams,
    rules: ItemRules,
    cfg: GeneratorConfig,
    *,
    weapon_kind: str | None,
    family_names: dict[str, str],
    rarity_names: dict[str, dict[str, str]],
) -> list[dict[str, Any]]:
    """-> [{code, data, l10n: {name: {locale: text}}}] — draft rows, not yet validated against the DB."""
    tiers = list(range(params.tier_from, params.tier_to + 1))
    rarities = allocate(params.rarity_weights, params.count)
    per_tier: dict[int, int] = {}
    slots: list[int] = []
    for i in range(params.count):
        tier = tiers[i * len(tiers) // params.count]
        per_tier[tier] = per_tier.get(tier, 0) + 1
        slots.append(tier)
    seen: dict[int, int] = {}
    family = params.weapon_family or params.armor_family or params.category
    curve = cfg.curves[curve_key(params.category, weapon_kind, params.armor_family)]
    out: list[dict[str, Any]] = []
    for i, (tier, rarity) in enumerate(zip(slots, rarities, strict=True)):
        k = seen.get(tier, 0)
        seen[tier] = k + 1
        gate = rules.gate(tier)
        span = gate.max_level - gate.min_level
        level = gate.min_level + (span * k // max(1, per_tier[tier] - 1) if per_tier[tier] > 1 else span // 2)
        mult = cfg.rarity_multipliers.get(rarity, 1.0) * cfg.slot_multipliers.get(params.slot, 1.0)
        base_stats = [{"stat": c.stat, "amount": round((c.base + c.per_level * level) * mult, 2)} for c in curve]
        n = i + 1
        fmt = {
            "theme": params.theme.code,
            "family": family,
            "slot": params.slot,
            "tier": tier,
            "rarity": rarity,
            "n": n,
        }
        code = params.code_pattern.format(**fmt).lower()
        names: dict[str, str] = {}
        for loc in LOCALES:
            pattern = params.name_patterns.get(loc)
            if pattern is None:
                continue
            names[loc] = pattern.format(
                theme=params.theme.names.get(loc, params.theme.names.get("en", params.theme.code)),
                family=family_names.get(loc, family_names.get("en", family)),
                tier=tier,
                rarity=rarity_names.get(rarity, {}).get(loc, rarity),
                n=n,
            )
        reqs = (
            suggested_requirements(rules, params.requirement_profile, level, tier) if params.requirement_profile else {}
        )
        unique = None
        if params.unique_effect and RARITY_ORDER.index(rarity) >= RARITY_ORDER.index("legendary"):
            unique = {
                **params.unique_effect,
                "mastery_scaling": rarity == "mythic" or params.unique_effect.get("mastery_scaling", False),
            }
        vendor = cfg.vendor_value
        data = {
            "category": params.category,
            "slot": params.slot,
            "family": family,
            "weapon_family": params.weapon_family,
            "armor_family": params.armor_family,
            "tier": tier,
            "min_level": level,
            "rarity": rarity,
            "requirement_profile": params.requirement_profile,
            "requirements": {"stats": {s: v for s, v in reqs.items() if v > 0}},
            "base_stats": base_stats,
            "affix_rules": {"pool": list(params.affix_pool), **({} if params.affix_pool else {"max": 0})},
            "unique_effect": unique,
            "class_tags": list(params.class_tags),
            "durability": {"max": cfg.durability.base + cfg.durability.per_tier * tier},
            "vendor_value": int(
                (vendor.base + vendor.per_level * level) * (RARITY_ORDER.index(rarity) + 1) ** vendor.rarity_pow
            ),
            "salvage": [{"template_code": params.salvage_material, "min_qty": 1, "max_qty": 1 + tier // 2}]
            if params.salvage_material
            else [],
            "sources": [{"kind": "drop"}],
            "icon": f"items/{family}_{params.slot}.svg",
        }
        out.append({"code": code, "data": data, "l10n": {"name": names}, "code_valid": bool(CODE_RE.match(code))})
    return out
