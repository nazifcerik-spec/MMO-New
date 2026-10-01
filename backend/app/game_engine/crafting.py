"""Pure crafting/gathering/enchanting math. Deterministic from seeds; the service handles persistence."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.game_engine.professions import ProfessionConfig, quality_chances, roll_quality
from app.game_engine.rng import Rng, derive_seed


class _S(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class GatheringConfig(_S):
    default_actions_per_hour: float = Field(gt=0, le=10_000)
    xp_per_action_base: float = Field(ge=0)
    xp_per_action_per_tier: float = Field(ge=0)


class SalvageConfig(_S):
    xp_per_item_base: float = Field(ge=0)
    xp_per_item_per_tier: float = Field(ge=0)
    profession: str


class EnchantingConfig(_S):
    level_per_tier: int = Field(ge=1, le=100)
    reroll_gold_base: int = Field(ge=0)
    reroll_gold_per_tier: int = Field(ge=0)
    reroll_material: str
    reroll_material_qty_base: int = Field(ge=0)
    reroll_material_qty_per_tier: int = Field(ge=0)
    reroll_xp: int = Field(ge=0)


class CraftingConfig(_S):
    max_active_jobs: int = Field(ge=1, le=20)
    max_batch: int = Field(ge=1, le=1000)
    xp_on_failure_pct: float = Field(ge=0, le=100)
    fail_chance_reduction_per_10_levels: float = Field(ge=0)
    min_fail_chance_pct: float = Field(ge=0, le=100)
    gathering: GatheringConfig
    salvage: SalvageConfig
    enchanting: EnchantingConfig
    workstations: tuple[str, ...] = ()


def fail_chance(cfg: CraftingConfig, base_pct: float, profession_level: int, required_level: int) -> float:
    over = max(0, profession_level - required_level)
    return max(cfg.min_fail_chance_pct, base_pct - (over / 10) * cfg.fail_chance_reduction_per_10_levels)


def resolve_craft(
    cfg: CraftingConfig,
    prof: ProfessionConfig,
    recipe: dict[str, Any],
    *,
    quantity: int,
    seed: int,
    profession_level: int,
    quality_bonus_pct: float,
) -> dict[str, Any]:
    """Per unit: failure roll → partial ingredient return; success → quality roll (if the recipe uses quality)."""
    rng = Rng(derive_seed(seed, "craft"))
    fail = fail_chance(cfg, recipe["fail_chance_pct"], profession_level, recipe["required_level"])
    chances = quality_chances(
        prof, profession_level=profession_level, recipe_level=recipe["required_level"], bonus_pct=quality_bonus_pct
    )
    outputs: dict[str, int] = {}
    failures = 0
    for _ in range(quantity):
        if rng.chance(fail):
            failures += 1
            continue
        q = roll_quality(prof, chances, rng) if recipe.get("quality_applies", True) else prof.quality_chain[0]
        outputs[q] = outputs.get(q, 0) + 1
    successes = quantity - failures
    returned = [
        {"template_code": ing["template_code"], "qty": ing["qty"] * failures * recipe["fail_return_pct"] // 100}
        for ing in recipe["ingredients"]
    ]
    xp = round(recipe["xp"] * successes + recipe["xp"] * failures * cfg.xp_on_failure_pct / 100)
    return {
        "successes": successes,
        "failures": failures,
        "fail_chance_pct": round(fail, 3),
        "quality_chances": chances,
        "outputs": dict(sorted(outputs.items())),
        "output_template": recipe["output"]["template_code"],
        "output_per_success": recipe["output"]["qty"],
        "returned": [r for r in returned if r["qty"] > 0],
        "xp": xp,
    }


def resolve_gathering(
    cfg: CraftingConfig,
    *,
    entries: list[dict[str, Any]],
    node_tier: int,
    actions_per_hour: float,
    segments: list[tuple[float, float]],  # (seconds, efficiency 0..1)
    speed_pct: float,
    yield_pct: float,
    rare_find_pct: float,
    seed: int,
) -> dict[str, Any]:
    """Actions happen at a (speed-scaled) rate; each action rolls one table entry. Efficiency and yield scale the
    quantity; rare entries' weight is boosted by rare find. Aggregated per action, bounded by duration."""
    rng = Rng(derive_seed(seed, "gather"))
    rate = actions_per_hour * (1 + speed_pct / 100) / 3600
    weights = [float(e["weight"]) * (1 + (rare_find_pct / 100 if e.get("rare") else 0)) for e in entries]
    total_actions = 0
    materials: dict[str, float] = {}
    xp = 0.0
    xp_each = cfg.gathering.xp_per_action_base + cfg.gathering.xp_per_action_per_tier * node_tier
    for seconds, eff in segments:
        n = int(seconds * rate)
        for _ in range(n):
            e = entries[rng.weighted_index(weights)]
            qty = rng.randint(int(e["min"]), int(e["max"])) * yield_pct / 100 * eff
            materials[e["template_code"]] = materials.get(e["template_code"], 0.0) + qty
            xp += xp_each * eff
        total_actions += n
    return {
        "actions": total_actions,
        "materials": {k: int(v) for k, v in sorted(materials.items()) if int(v) > 0},
        "xp": round(xp),
    }


def reroll_value(rolls: list[dict[str, Any]], tier: int, seed: int) -> float | None:
    rng = Rng(derive_seed(seed, "reroll"))
    for r in rolls:
        if r["tier_from"] <= tier <= r["tier_to"]:
            v = rng.uniform(float(r["min"]), float(r["max"]))
            return round(v, 2) if abs(r["max"]) < 20 else float(round(v))
    return None


def salvage_outputs(salvage: list[dict[str, Any]], seed: int, yield_pct: float) -> dict[str, int]:
    rng = Rng(derive_seed(seed, "salvage"))
    out: dict[str, int] = {}
    for s in salvage:
        if not rng.chance(float(s.get("chance_pct", 100))):
            continue
        qty = int(rng.randint(int(s["min_qty"]), int(s["max_qty"])) * yield_pct / 100)
        if qty > 0:
            out[s["template_code"]] = out.get(s["template_code"], 0) + qty
    return out
