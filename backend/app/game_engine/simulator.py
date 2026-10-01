"""Pure helpers for the balance simulator/checker: synthetic gear, greedy talent builds, metric aggregation."""

import statistics
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.game_engine.item_generator import GeneratorConfig
from app.game_engine.items import ItemRules
from app.game_engine.talents import NodeDef, TalentConfig, points_for_level, validate_allocation


class _S(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Limits(_S):
    max_iterations: int = Field(ge=1, le=200)
    max_fights: int = Field(ge=1, le=500)
    max_duration_s: int = Field(ge=60, le=10800)


class CheckerConfig(_S):
    racial_target_pct: float
    racial_warn_pct: float
    support_band_pct: tuple[float, float]
    dominance_warn_pct: float
    fights: int = Field(ge=1, le=100)


class SimulatorConfig(_S):
    class_gear: dict[str, dict[str, str]]
    stat_profile: dict[str, str]
    armor_slots: tuple[str, ...]
    limits: Limits
    checker: CheckerConfig


def synthetic_gear(
    cfg: SimulatorConfig, gen: GeneratorConfig, rules: ItemRules, class_code: str, tier: int, budget_pct: float
) -> list[dict[str, Any]]:
    """STAT_FLAT effects equal to a full set of tier-`tier` gear (first rarity of the tier band) × budget%."""
    if tier < 0:
        return []
    gate = rules.gate(tier)
    level = gate.min_level
    rarity_mult = gen.rarity_multipliers.get(gate.rarities[0], 1.0) * budget_pct / 100
    kit = cfg.class_gear.get(class_code, {"weapon": "weapon_melee", "armor": "armor_cloth"})
    totals: dict[str, float] = {}
    pieces = [(kit["weapon"], "main_hand")] + [(kit["armor"], s) for s in cfg.armor_slots]
    for curve_key, slot in pieces:
        for c in gen.curves.get(curve_key, []):
            totals[c.stat] = (
                totals.get(c.stat, 0.0)
                + (c.base + c.per_level * level) * gen.slot_multipliers.get(slot, 1.0) * rarity_mult
            )
    return [
        {"effect_type": "STAT_FLAT", "params": {"stat": k, "amount": round(v, 2)}} for k, v in sorted(totals.items())
    ]


def greedy_talents(defs: dict[str, NodeDef], level: int, cfg: TalentConfig, focus: list[str]) -> dict[str, int]:
    """Spend all points: focus trees first, low tiers first; every step stays a valid allocation."""
    budget = points_for_level(cfg, level)
    order = sorted(
        defs.values(), key=lambda n: (focus.index(n.tree) if n.tree in focus else len(focus), n.tier, n.code)
    )
    alloc: dict[str, int] = {}
    progressed = True
    while sum(alloc.values()) < budget and progressed:
        progressed = False
        for n in order:
            if alloc.get(n.code, 0) >= n.max_rank:
                continue
            trial = {**alloc, n.code: alloc.get(n.code, 0) + 1}
            if not validate_allocation(defs, trial, level, cfg):
                alloc = trial
                progressed = True
                break
    return alloc


def summarize(values: list[float]) -> dict[str, float]:
    if not values:
        return {"mean": 0.0, "min": 0.0, "max": 0.0, "stdev": 0.0}
    return {
        "mean": round(statistics.fmean(values), 3),
        "min": round(min(values), 3),
        "max": round(max(values), 3),
        "stdev": round(statistics.pstdev(values), 3),
    }


def pct_delta(value: float, reference: float) -> float:
    return round(100 * (value - reference) / reference, 2) if reference else 0.0
