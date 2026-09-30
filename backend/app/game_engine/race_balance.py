"""Estimate the total combat advantage of a set of (racial) effects, in percent. Pure and config-driven."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.game_engine.effects import validate_effect
from app.game_engine.stats import PRIMARY_STATS


class RaceBalanceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    warn_percent: float = Field(gt=0)
    error_percent: float = Field(gt=0)
    primary_stat_weight: float = Field(ge=0, le=2)
    stat_percent_weights: dict[str, float] = Field(default_factory=dict)
    stat_flat_weights: dict[str, float] = Field(default_factory=dict)
    default_stat_weight: float = Field(ge=0, le=2)
    damage_multiplier_weight: float = Field(ge=0, le=2)
    heal_multiplier_weight: float = Field(ge=0, le=2)
    condition_uptime: dict[str, float] = Field(default_factory=dict)
    default_condition_uptime: float = Field(ge=0, le=1)
    non_combat_effects: list[str] = Field(default_factory=list)


def _estimate(cfg: RaceBalanceConfig, raw: dict[str, Any], uptime: float, lines: list[dict[str, Any]]) -> float:
    et = raw["effect_type"]
    p = raw.get("params", {})
    value = 0.0
    if et in cfg.non_combat_effects:
        value = 0.0
    elif et == "STAT_PERCENT":
        w = (
            cfg.primary_stat_weight
            if p["stat"] in PRIMARY_STATS
            else cfg.stat_percent_weights.get(p["stat"], cfg.default_stat_weight)
        )
        value = abs(p["percent"]) * w * (1 if p["percent"] >= 0 else -1)
    elif et == "STAT_FLAT":
        value = p["amount"] * cfg.stat_flat_weights.get(p["stat"], cfg.default_stat_weight)
    elif et == "DAMAGE_MULTIPLIER":
        cond = p.get("condition")
        u = cfg.condition_uptime.get(cond["metric"], cfg.default_condition_uptime) if cond else 1.0
        value = p["percent"] * cfg.damage_multiplier_weight * u
    elif et == "HEAL_MULTIPLIER":
        value = p["percent"] * cfg.heal_multiplier_weight
    elif et == "THRESHOLD_TRIGGER":
        cond = p["condition"]
        u = cfg.condition_uptime.get(cond["metric"], cfg.default_condition_uptime)
        return sum(_estimate(cfg, e, uptime * u, lines) for e in p["effects"])
    elif et in ("AURA",):
        return sum(_estimate(cfg, e, uptime, lines) for e in p["effects"])
    else:
        value = cfg.default_stat_weight * float(p.get("percent", 0) or 0)
    value *= uptime
    lines.append({"effect_type": et, "estimate": round(value, 3)})
    return value


def estimate_combat_advantage(
    cfg: RaceBalanceConfig, effects: list[dict[str, Any]]
) -> tuple[float, list[dict[str, Any]]]:
    lines: list[dict[str, Any]] = []
    total = 0.0
    for e in effects:
        validate_effect(e)
        total += _estimate(cfg, e, 1.0, lines)
    return round(total, 3), lines
