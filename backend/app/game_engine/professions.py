"""Pure profession rules: XP curve (independent of character XP), ranks, license cap, stat influence
(speed/quality only — never hard locks), tool-tier yield, node access and crafting quality rolls."""

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.game_engine.rng import Rng


class _S(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Rank(_S):
    code: str
    min_level: int = Field(ge=1, le=500)


class XpCurve(_S):
    base: float = Field(gt=0)
    per_level: float = Field(ge=0)
    exponent: float = Field(ge=1, le=3)


class CostBand(_S):
    min_level: int = Field(ge=1, le=500)
    gold: int = Field(ge=0)


class LicenseConfig(_S):
    max_active: int = Field(ge=1, le=15)
    free_activations: int = Field(ge=0, le=15)
    swap_cooldown_s: int = Field(ge=0)
    swap_cost_gold: tuple[CostBand, ...] = Field(min_length=1)
    respecialize_cost_gold: int = Field(ge=0)


class StatConfig(_S):
    speed_pct_per_point: float = Field(ge=0)
    speed_cap_pct: float = Field(ge=0, le=100)
    quality_pct_per_point: float = Field(ge=0)
    quality_cap_pct: float = Field(ge=0, le=100)


class ToolConfig(_S):
    below_tier_yield_penalty_pct: float = Field(ge=0, le=100)
    min_yield_pct: float = Field(ge=0, le=100)
    above_tier_bonus_pct: float = Field(ge=0)
    above_tier_bonus_cap_pct: float = Field(ge=0)


class ProfessionConfig(_S):
    level_cap: int = Field(ge=1, le=500)
    ranks: tuple[Rank, ...] = Field(min_length=1)
    specialization_level: int = Field(ge=1, le=500)
    unlicensed_level_cap: int = Field(ge=1, le=500)
    xp_curve: XpCurve
    license: LicenseConfig
    stats: StatConfig
    tools: ToolConfig
    node_level_per_tier: int = Field(ge=1, le=100)
    quality_chain: tuple[str, ...] = Field(min_length=2)
    quality_base_chances: dict[str, float]
    quality_level_bonus_pct_per_10_over: float = Field(ge=0)

    @model_validator(mode="after")
    def _check(self) -> "ProfessionConfig":
        if self.ranks[0].min_level != 1 or [r.min_level for r in self.ranks] != sorted(r.min_level for r in self.ranks):
            raise ValueError("ranks must start at 1 and increase")
        if set(self.quality_base_chances) != set(self.quality_chain[1:]):
            raise ValueError("quality chances must cover every quality above the base")
        return self


def xp_to_next(cfg: ProfessionConfig, level: int) -> int | None:
    if level >= cfg.level_cap:
        return None
    c = cfg.xp_curve
    value: float = c.base + c.per_level * float(level) ** c.exponent
    return max(1, round(value))


def rank_for(cfg: ProfessionConfig, level: int) -> str:
    return [r.code for r in cfg.ranks if level >= r.min_level][-1]


@dataclass(frozen=True, slots=True)
class XpApplied:
    level: int
    xp: int
    levels_gained: int
    capped_by_license: bool
    reached_cap: bool


def apply_xp(cfg: ProfessionConfig, level: int, xp: int, gain: int, *, licensed: bool) -> XpApplied:
    """Add profession XP. Unlicensed professions stop at `unlicensed_level_cap` (XP is not banked above it)."""
    cap = cfg.level_cap if licensed else min(cfg.level_cap, cfg.unlicensed_level_cap)
    start = level
    xp += max(0, gain)
    capped = False
    while True:
        need = xp_to_next(cfg, level)
        if need is None or xp < need:
            break
        if level >= cap:
            capped = True
            xp = need - 1  # hold just below the gate; no infinite banking
            break
        xp -= need
        level += 1
    if level >= cfg.level_cap:
        xp = 0
    return XpApplied(level, xp, level - start, capped, level >= cfg.level_cap)


def swap_cost(cfg: ProfessionConfig, level: int) -> int:
    return [b.gold for b in cfg.license.swap_cost_gold if level >= b.min_level][-1] if level >= 1 else 0


def stat_bonuses(cfg: ProfessionConfig, stats: dict[str, float], relevant: list[str]) -> dict[str, float]:
    """Relevant-stat average → speed and quality bonus percentages (capped)."""
    if not relevant:
        return {"speed": 0.0, "quality": 0.0}
    avg = sum(stats.get(s, 0.0) for s in relevant) / len(relevant)
    return {
        "speed": round(min(cfg.stats.speed_cap_pct, avg * cfg.stats.speed_pct_per_point), 3),
        "quality": round(min(cfg.stats.quality_cap_pct, avg * cfg.stats.quality_pct_per_point), 3),
    }


def tool_yield_pct(cfg: ProfessionConfig, tool_tier: int | None, node_tier: int) -> float:
    """No tool counts as tier -1. Below the node tier: heavy loss per tier; above: small capped bonus."""
    t = -1 if tool_tier is None else tool_tier
    gap = node_tier - t
    if gap > 0:
        return max(cfg.tools.min_yield_pct, 100 - gap * cfg.tools.below_tier_yield_penalty_pct)
    return 100 + min(cfg.tools.above_tier_bonus_cap_pct, -gap * cfg.tools.above_tier_bonus_pct)


def node_level_required(cfg: ProfessionConfig, node_tier: int) -> int:
    return max(1, node_tier * cfg.node_level_per_tier)


def quality_chances(
    cfg: ProfessionConfig, *, profession_level: int, recipe_level: int, bonus_pct: float
) -> dict[str, float]:
    """Chance per quality above the base; over-levelling the recipe and quality bonuses scale them up."""
    over = max(0, profession_level - recipe_level)
    mult = 1 + (over / 10) * cfg.quality_level_bonus_pct_per_10_over / 100 + bonus_pct / 100
    return {q: round(min(95.0, c * mult), 4) for q, c in cfg.quality_base_chances.items()}


def roll_quality(cfg: ProfessionConfig, chances: dict[str, float], rng: Rng) -> str:
    """Try the best quality first; a single uniform draw keeps it deterministic and monotonic."""
    x = rng.random() * 100
    acc = 0.0
    for q in reversed(cfg.quality_chain[1:]):
        acc += chances.get(q, 0.0)
        if x < acc:
            return q
    return cfg.quality_chain[0]


def yield_modifiers(effects: list[dict[str, Any]], profession: str) -> dict[str, float]:
    """Sum PROFESSION_YIELD_MOD effects (from any source) for one profession, by kind."""
    out: dict[str, float] = {"yield": 0.0, "speed": 0.0, "quality": 0.0, "rare_find": 0.0, "xp": 0.0}
    for e in effects:
        if e.get("effect_type") != "PROFESSION_YIELD_MOD":
            continue
        p = e["params"]
        if p["profession"] in (profession, "*"):
            out[p["kind"]] += float(p["percent"])
    return out
