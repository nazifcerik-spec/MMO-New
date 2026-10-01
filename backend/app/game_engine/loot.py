"""Loot rules: weighted drop tables with conditions, rarity rolls, LUK (diminishing), pity, ownership limits.

Pure functions; the AFK engine stores `LootConfig` in session snapshots so live balance edits never change
old sessions."""

from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.game_engine.items import RARITY_ORDER
from app.game_engine.rng import Rng


class _S(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class LuckConfig(_S):
    max_rare_bonus_pct: float = Field(ge=0, le=100)
    half_point: float = Field(gt=0)
    max_quantity_bonus_pct: float = Field(default=0, ge=0, le=50)


class PityConfig(_S):
    enabled: bool = True
    threshold_fights: int = Field(ge=1, le=100_000)
    show_progress_for: tuple[str, ...] = ()


class LootConfig(_S):
    luck: LuckConfig
    rarity_weights: dict[str, float]
    rare_threshold: str = "rare"
    pity: PityConfig
    owned_limits: dict[str, int] = {}

    @model_validator(mode="after")
    def _check(self) -> "LootConfig":
        for r in (*self.rarity_weights, self.rare_threshold, *self.owned_limits):
            if r not in RARITY_ORDER:
                raise ValueError(f"unknown rarity {r}")
        if not sum(self.rarity_weights.values()) > 0 or any(w < 0 for w in self.rarity_weights.values()):
            raise ValueError("rarity_weights need a positive total")
        return self


def luck_bonus(cfg: LootConfig, luk: float) -> float:
    """Diminishing-return rare bonus %: approaches but never exceeds `max_rare_bonus_pct`."""
    luk = max(0.0, luk)
    return round(cfg.luck.max_rare_bonus_pct * luk / (luk + cfg.luck.half_point), 4)


def is_rare(cfg: LootConfig, rarity: str | None) -> bool:
    return rarity is not None and RARITY_ORDER.index(rarity) >= RARITY_ORDER.index(cfg.rare_threshold)


def roll_rarity(cfg: LootConfig, rng: Rng, rare_bonus_pct: float, *, force_rare: bool = False) -> str:
    """Rarities at/above the rare threshold get their weight scaled by (1 + bonus%)."""
    items = []
    for r, w in cfg.rarity_weights.items():
        if force_rare and not is_rare(cfg, r):
            continue
        items.append((r, w * (1 + rare_bonus_pct / 100) if is_rare(cfg, r) else w))
    total = sum(w for _, w in items)
    pick = rng.uniform(0, total)
    acc = 0.0
    for r, w in items:
        acc += w
        if pick <= acc:
            return r
    return items[-1][0]


def entry_eligible(entry: dict[str, Any], ctx: dict[str, Any]) -> bool:
    """Conditions: boss_only, zone codes/tags, character level range."""
    if entry.get("boss_only") and not ctx.get("boss"):
        return False
    cond = entry.get("conditions") or {}
    if cond.get("zone_codes") and ctx.get("zone_code") not in cond["zone_codes"]:
        return False
    if cond.get("zone_tags") and not set(cond["zone_tags"]) & set(ctx.get("zone_tags", ())):
        return False
    level = int(ctx.get("level", 1))
    if level < int(cond.get("min_level", 1)) or level > int(cond.get("max_level", 1000)):
        return False
    return True


def _weighted(rng: Rng, entries: Sequence[dict[str, Any]]) -> dict[str, Any] | None:
    total = sum(float(e["weight"]) for e in entries)
    if total <= 0:
        return None
    pick = rng.uniform(0, total)
    acc = 0.0
    for e in entries:
        acc += float(e["weight"])
        if pick <= acc:
            return e
    return entries[-1]


def roll_table(
    cfg: LootConfig,
    rng: Rng,
    rolls: int,
    entries: Sequence[dict[str, Any]],
    ctx: dict[str, Any],
    *,
    rare_bonus_pct: float,
    force_rare: bool,
) -> list[dict[str, Any]]:
    """Each roll picks one eligible entry, applies its chance, then (for item pools) rolls rarity.
    `force_rare` (pity) restricts the first roll to rare-capable entries and guarantees a rare result."""
    eligible = [e for e in entries if entry_eligible(e, ctx)]
    out: list[dict[str, Any]] = []
    for n in range(rolls):
        pool = eligible
        forced = force_rare and n == 0
        if forced:
            pool = [e for e in eligible if e.get("rare") or (e["kind"] == "item_pool" and not e.get("rarity"))]
            if not pool:
                forced, pool = False, eligible
        entry = _weighted(rng, pool)
        if entry is None or entry["kind"] == "nothing":
            continue
        chance = float(entry.get("chance_pct", 100))
        if entry.get("rare"):
            chance = min(100.0, chance * (1 + rare_bonus_pct / 100))
        if not forced and not rng.chance(chance):
            continue
        qty = rng.randint(int(entry.get("min_qty", 1)), int(entry.get("max_qty", 1)))
        drop = {k: v for k, v in entry.items() if k not in ("weight", "chance_pct", "min_qty", "max_qty", "conditions")}
        if entry["kind"] == "item_pool" and not entry.get("rarity"):
            drop["rarity"] = roll_rarity(cfg, rng, rare_bonus_pct, force_rare=forced)
        drop["rare"] = bool(entry.get("rare")) or is_rare(cfg, drop.get("rarity"))
        drop["qty"] = qty
        out.append(drop)
    return out


def pity_visible(cfg: LootConfig, content_kind: str) -> bool:
    return cfg.pity.enabled and content_kind in cfg.pity.show_progress_for
