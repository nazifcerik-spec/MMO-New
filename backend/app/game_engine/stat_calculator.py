"""Single source of truth for character stats: base + race + class + allocated + equipment + talent + buff.

Sources contribute flat/percent modifiers (from STAT_FLAT / STAT_PERCENT effects). Primary stats go through
soft caps before percent bonuses; derived stats use config formulas. Every number keeps a breakdown."""

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from app.game_engine.effects import StatFlat, StatPercent, validate_effect
from app.game_engine.progression import ProgressionConfig, effective_stat
from app.game_engine.stats import PRIMARY_STATS

SOURCE_ORDER = ("base", "race", "class", "allocated", "equipment", "talent", "buff")


@dataclass(slots=True)
class Contribution:
    source: str
    ref: str
    flat: dict[str, float] = field(default_factory=dict)
    percent: dict[str, float] = field(default_factory=dict)


def contribution_from_effects(source: str, ref: str, effects: Iterable[dict[str, Any]]) -> Contribution:
    """Collect unconditional stat effects; conditional/trigger effects are resolved by the combat engine."""
    c = Contribution(source, ref)
    for raw in effects:
        params = validate_effect(raw)
        if isinstance(params, StatFlat):
            c.flat[params.stat] = c.flat.get(params.stat, 0.0) + params.amount
        elif isinstance(params, StatPercent):
            c.percent[params.stat] = c.percent.get(params.stat, 0.0) + params.percent
    return c


@dataclass(slots=True)
class StatLine:
    code: str
    raw: float
    effective: float
    percent_bonus: float
    final: float
    breakdown: list[dict[str, Any]]


@dataclass(slots=True)
class StatSheet:
    level: int
    primary: dict[str, StatLine]
    derived: dict[str, StatLine]

    def value(self, code: str) -> float:
        line = self.primary.get(code) or self.derived.get(code)
        return line.final if line else 0.0

    def as_dict(self) -> dict[str, Any]:
        def _line(sl: StatLine) -> dict[str, Any]:
            return {
                "code": sl.code,
                "raw": round(sl.raw, 4),
                "effective": round(sl.effective, 4),
                "percent_bonus": round(sl.percent_bonus, 4),
                "final": round(sl.final, 4),
                "breakdown": sl.breakdown,
            }

        return {
            "level": self.level,
            "primary": {k: _line(v) for k, v in self.primary.items()},
            "derived": {k: _line(v) for k, v in self.derived.items()},
        }

    def finals(self) -> dict[str, float]:
        return {**{k: v.final for k, v in self.primary.items()}, **{k: v.final for k, v in self.derived.items()}}


def compute_stat_sheet(cfg: ProgressionConfig, level: int, contributions: list[Contribution]) -> StatSheet:
    contribs = [Contribution("base", "base", {s: float(cfg.base_primary_stat) for s in PRIMARY_STATS}), *contributions]
    unknown = {c.source for c in contribs} - set(SOURCE_ORDER)
    if unknown:
        raise ValueError(f"unknown stat sources {sorted(unknown)}")
    contribs.sort(key=lambda c: SOURCE_ORDER.index(c.source))

    def gather(code: str) -> tuple[float, float, list[dict[str, Any]]]:
        flat = pct = 0.0
        bd: list[dict[str, Any]] = []
        for c in contribs:
            f, p = c.flat.get(code, 0.0), c.percent.get(code, 0.0)
            if f or p:
                bd.append({"source": c.source, "ref": c.ref, "flat": f, "percent": p})
                flat += f
                pct += p
        return flat, pct, bd

    primary: dict[str, StatLine] = {}
    for s in PRIMARY_STATS:
        flat, pct, bd = gather(s)
        eff = effective_stat(cfg, flat)
        primary[s] = StatLine(s, flat, eff, pct, eff * (1 + pct / 100.0), bd)

    derived: dict[str, StatLine] = {}
    for code, f in cfg.derived.items():
        base_value = f.base + f.per_level * level + sum(k * primary[s].final for s, k in f.per_stat.items())
        flat, pct, bd = gather(code)
        bd.insert(0, {"source": "formula", "ref": code, "flat": round(base_value, 4), "percent": 0.0})
        value = (base_value + flat) * (1 + pct / 100.0)
        cap = cfg.caps.get(code)
        if cap is not None:
            value = min(value, cap)
        derived[code] = StatLine(code, base_value + flat, base_value + flat, pct, max(value, 0.0), bd)
    return StatSheet(level, primary, derived)


def allocation_contribution(allocations: dict[str, int]) -> Contribution:
    return Contribution("allocated", "allocated", {s: float(n) for s, n in allocations.items() if n})
