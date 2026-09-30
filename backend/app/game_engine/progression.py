"""Pure progression math: XP curve, level-ups, soft caps, titles, breakpoints, stat templates, respec quote.

All inputs come from the published `progression` balance config; nothing here touches the DB."""

import itertools
import math
from dataclasses import dataclass
from functools import cached_property
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.game_engine.stats import DERIVED_STATS, PRIMARY_STATS


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SoftCapBand(_Strict):
    upto: int | None = Field(default=None, ge=1)
    effectiveness: float = Field(gt=0, le=1)


class TitleStep(_Strict):
    level: int = Field(ge=1, le=1000)
    code: str = Field(pattern=r"^[a-z_]+$")


class XpSegment(_Strict):
    from_level: int = Field(ge=1)
    to_level: int = Field(ge=2)
    hours: float = Field(gt=0)
    ramp: float = Field(ge=1.0, le=10.0)  # hours(last level)/hours(first level) within the segment


class ReferenceRate(_Strict):
    base: float = Field(gt=0)
    exponent: float = Field(ge=0, le=3)


class XpCurve(_Strict):
    segments: list[XpSegment] = Field(min_length=1)
    reference_xp_per_hour: ReferenceRate


class RespecBand(_Strict):
    min_level: int = Field(ge=1)
    gold_per_point: int = Field(ge=0)


class RespecConfig(_Strict):
    free_below_level: int = Field(ge=1)
    bands: list[RespecBand]
    cooldown_seconds: int = Field(ge=0)


class DerivedFormula(_Strict):
    base: float
    per_level: float = 0
    per_stat: dict[str, float] = Field(default_factory=dict)


class ProgressionConfig(_Strict):
    level_cap: int = Field(ge=2, le=1000)
    stat_points_per_level: int = Field(ge=1, le=10)
    breakpoints: list[int]
    base_primary_stat: int = Field(ge=0, le=100)
    soft_cap_bands: list[SoftCapBand] = Field(min_length=1)
    titles: list[TitleStep] = Field(min_length=1)
    xp_curve: XpCurve
    respec: RespecConfig
    derived: dict[str, DerivedFormula]
    caps: dict[str, float] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check(self) -> "ProgressionConfig":
        if sorted(self.breakpoints) != self.breakpoints:
            raise ValueError("breakpoints must be ascending")
        if self.soft_cap_bands[-1].upto is not None:
            raise ValueError("last soft cap band must be open-ended (upto: null)")
        uppers = [b.upto for b in self.soft_cap_bands[:-1]]
        if any(u is None for u in uppers) or uppers != sorted(uppers):  # type: ignore[type-var]
            raise ValueError("soft cap bands must be ascending")
        if [t.level for t in self.titles] != sorted(t.level for t in self.titles) or self.titles[0].level != 1:
            raise ValueError("titles must start at level 1 and ascend")
        segs = self.xp_curve.segments
        if segs[0].from_level != 1 or segs[-1].to_level != self.level_cap:
            raise ValueError("xp segments must span 1..level_cap")
        for a, b in itertools.pairwise(segs):
            if a.to_level != b.from_level:
                raise ValueError("xp segments must be contiguous")
        unknown = set(self.derived) - set(DERIVED_STATS)
        if unknown:
            raise ValueError(f"unknown derived stats {sorted(unknown)}")
        for name, f in self.derived.items():
            bad = set(f.per_stat) - set(PRIMARY_STATS)
            if bad:
                raise ValueError(f"{name}: unknown primary stats {sorted(bad)}")
        return self

    @cached_property
    def xp_table(self) -> tuple[int, ...]:
        """xp_table[L] = XP required to go from level L to L+1 (index 0 unused, cap level = 0)."""
        return build_xp_table(self)


def reference_xp_per_hour(cfg: ProgressionConfig, level: int) -> float:
    r = cfg.xp_curve.reference_xp_per_hour
    return r.base * math.pow(level, r.exponent)


def hours_for_level(seg: XpSegment, level: int) -> float:
    """Linear ramp of hours/level inside a segment whose sum equals seg.hours."""
    n = seg.to_level - seg.from_level
    i = level - seg.from_level
    if n == 1:
        return seg.hours
    first = 2 * seg.hours / (n * (1 + seg.ramp))
    return first * (1 + (seg.ramp - 1) * i / (n - 1))


def build_xp_table(cfg: ProgressionConfig) -> tuple[int, ...]:
    table = [0] * (cfg.level_cap + 1)
    for seg in cfg.xp_curve.segments:
        for level in range(seg.from_level, seg.to_level):
            table[level] = max(1, round(hours_for_level(seg, level) * reference_xp_per_hour(cfg, level)))
    return tuple(table)


def xp_to_next(cfg: ProgressionConfig, level: int) -> int | None:
    return None if level >= cfg.level_cap else cfg.xp_table[level]


@dataclass(frozen=True, slots=True)
class XpResult:
    level: int
    xp: int  # progress inside the current level
    levels_gained: int
    stat_points_gained: int
    overflow_xp: int  # XP past the cap (feeds horizontal mastery)
    breakpoints_crossed: tuple[int, ...]


def apply_xp(cfg: ProgressionConfig, level: int, xp: int, gain: int) -> XpResult:
    if gain < 0:
        raise ValueError("XP gain must be non-negative")
    if not 1 <= level <= cfg.level_cap:
        raise ValueError("level out of range")
    start = level
    xp += gain
    overflow = 0
    while level < cfg.level_cap:
        need = cfg.xp_table[level]
        if xp < need:
            break
        xp -= need
        level += 1
    if level >= cfg.level_cap:
        overflow, xp = xp, 0
    gained = level - start
    crossed = tuple(b for b in cfg.breakpoints if start < b <= level)
    return XpResult(level, xp, gained, gained * cfg.stat_points_per_level, overflow, crossed)


def total_points_for_level(cfg: ProgressionConfig, level: int) -> int:
    return (level - 1) * cfg.stat_points_per_level


def effective_stat(cfg: ProgressionConfig, raw: float) -> float:
    """Apply soft-cap bands to a raw flat stat total (e.g. 700 -> 300 + 300*0.7 + 100*0.45)."""
    remaining, lower, total = max(raw, 0.0), 0, 0.0
    for band in cfg.soft_cap_bands:
        upper = band.upto if band.upto is not None else math.inf
        span = min(remaining, upper - lower)
        if span <= 0:
            break
        total += span * band.effectiveness
        remaining -= span
        lower = int(upper) if upper != math.inf else lower
    return total


def title_for_level(cfg: ProgressionConfig, level: int) -> str:
    code = cfg.titles[0].code
    for t in cfg.titles:
        if level >= t.level:
            code = t.code
    return code


def next_title(cfg: ProgressionConfig, level: int) -> TitleStep | None:
    return next((t for t in cfg.titles if t.level > level), None)


def next_breakpoint(cfg: ProgressionConfig, level: int) -> int | None:
    return next((b for b in cfg.breakpoints if b > level), None)


# ---------------------------------------------------------------- allocation templates
StatTokens = dict[str, str]  # token (main/secondary/utility/main_damage) -> stat code


def resolve_profile_weights(weights: dict[str, float], tokens: StatTokens) -> dict[str, float]:
    """Expand tokens and `A|B` splits into concrete stat weights (merged)."""
    out: dict[str, float] = {s: 0.0 for s in PRIMARY_STATS}
    for key, weight in weights.items():
        parts = key.split("|")
        stats = [tokens.get(p, p) for p in parts]
        for s in stats:
            if s not in out:
                raise ValueError(f"unresolved stat token '{s}'")
            out[s] += weight / len(stats)
    return {k: v for k, v in out.items() if v > 0}


def distribute_points(points: int, weights: dict[str, float]) -> dict[str, int]:
    """Deterministic largest-remainder distribution; ties broken by canonical stat order."""
    if points < 0:
        raise ValueError("points must be non-negative")
    total = sum(weights.values())
    if total <= 0:
        raise ValueError("weights must be positive")
    exact = {s: points * w / total for s, w in weights.items()}
    alloc = {s: math.floor(v) for s, v in exact.items()}
    left = points - sum(alloc.values())
    order = sorted(exact, key=lambda s: (-(exact[s] - alloc[s]), PRIMARY_STATS.index(s)))
    for s in order[:left]:
        alloc[s] += 1
    return {s: n for s, n in alloc.items() if n}


def respec_cost(
    cfg: ProgressionConfig,
    level: int,
    points: int,
    *,
    discount_percent: float = 0.0,
    discount_limit_points: int | None = None,
) -> int:
    """Gold cost to refund `points`. Discount (e.g. Human) applies only to the first N points."""
    if level < cfg.respec.free_below_level or points <= 0:
        return 0
    rate = 0
    for band in cfg.respec.bands:
        if level >= band.min_level:
            rate = band.gold_per_point
    discounted = min(points, discount_limit_points) if discount_limit_points is not None else points
    full = points - discounted
    cost = full * rate + discounted * rate * (1 - discount_percent / 100.0)
    return max(0, math.ceil(cost))


Stance = Literal["manual", "template"]
