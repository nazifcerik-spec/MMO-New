"""Deterministic AFK session resolution (ADR-0002).

No real-time loop: a bounded number of full combat simulations are sampled from the immutable snapshot, then
the elapsed period is walked fight-by-fight with cheap seeded rolls (encounter composition, outcome from the
sampled win rate, drops). Same snapshot + seed + elapsed ⇒ identical result."""

import hashlib
import json
import math
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.game_engine.combat.engine import simulate
from app.game_engine.combat.models import CombatantSnapshot, CombatConfig, CombatInput, CombatStrategy
from app.game_engine.combat.rules import rule_selector, validate_rules
from app.game_engine.rng import Rng, derive_seed
from app.game_engine.world import ZoneBundle, enemy_rules, generate_encounter, roll_drops, rules_by_code_selector


class _S(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class EfficiencyBand(_S):
    from_hours: float = Field(ge=0, le=24)
    to_hours: float = Field(gt=0, le=24)
    percent: int = Field(ge=0, le=100)


class OverLevelPenalty(_S):
    grace_levels: int = Field(default=20, ge=0, le=1000)
    per_level_pct: float = Field(default=3, ge=0, le=100)
    min_pct: float = Field(default=10, ge=0, le=100)


class RestedConfig(_S):
    """Extension point; disabled by default so it cannot be exploited before it is designed/tested."""

    enabled: bool = False
    accrue_pct_per_offline_hour: float = Field(default=0, ge=0, le=100)
    max_bonus_pct: float = Field(default=0, ge=0, le=100)


class AfkBalance(_S):
    max_session_seconds: int = Field(gt=0, le=10_800)  # canonical hard cap: 3 h
    min_session_seconds: int = Field(ge=60, le=3600)
    player_day_reset_hour_utc: int = Field(ge=0, le=23)
    daily_efficiency_bands: tuple[EfficiencyBand, ...] = Field(min_length=1)
    rested_bonus_enabled: bool = False
    rested: RestedConfig = RestedConfig()
    sample_fights: int = Field(default=24, ge=4, le=200)
    boss_sample_fights: int = Field(default=4, ge=0, le=50)
    max_fights: int = Field(default=3000, ge=10, le=20_000)
    downtime_base_s: float = Field(default=6, ge=0, le=600)
    rest_full_hp_s: float = Field(default=30, ge=0, le=3600)
    death_recovery_s: float = Field(default=1200, ge=0, le=3600)  # canonical 15-30 min of lost efficiency
    death_gold_cost_pct: float = Field(default=2, ge=0, le=50)
    durability_loss_per_death_pct: float = Field(default=5, ge=0, le=100)
    reference_cycle_s: float = Field(default=50, gt=0, le=3600)
    reference_units_per_fight: float = Field(default=3, gt=0, le=20)
    over_level: OverLevelPenalty = OverLevelPenalty()
    pity_threshold_fights: int = Field(default=150, ge=1, le=100_000)
    timeline_bucket_s: int = Field(default=1800, ge=300, le=10_800)

    @model_validator(mode="after")
    def _bands(self) -> "AfkBalance":
        cursor, last = 0.0, 101
        for b in self.daily_efficiency_bands:
            if b.from_hours != cursor or b.to_hours <= b.from_hours:
                raise ValueError("efficiency bands must be contiguous and increasing from 0h")
            if b.percent > last:
                raise ValueError("efficiency must not increase over the day")
            cursor, last = b.to_hours, b.percent
        if cursor != 24:
            raise ValueError("efficiency bands must cover 0-24h")
        if self.min_session_seconds > self.max_session_seconds:
            raise ValueError("min_session_seconds > max_session_seconds")
        return self


# --------------------------------------------------------------------------- player-day efficiency
class Segment(_S):
    start_s: float  # offset from session start
    end_s: float
    percent: int
    day: date


def player_day(cfg: AfkBalance, at: datetime) -> date:
    return (at.astimezone(UTC) - timedelta(hours=cfg.player_day_reset_hour_utc)).date()


def day_start(cfg: AfkBalance, day: date) -> datetime:
    return datetime(day.year, day.month, day.day, tzinfo=UTC) + timedelta(hours=cfg.player_day_reset_hour_utc)


def day_slices(cfg: AfkBalance, start: datetime, duration_s: float) -> list[tuple[date, float]]:
    """Split [start, start+duration) at player-day boundaries."""
    out: list[tuple[date, float]] = []
    t, end = start, start + timedelta(seconds=duration_s)
    while t < end:
        d = player_day(cfg, t)
        boundary = min(end, day_start(cfg, d) + timedelta(days=1))
        out.append((d, (boundary - t).total_seconds()))
        t = boundary
    return out


def efficiency_segments(
    cfg: AfkBalance, start: datetime, duration_s: float, prior_seconds: dict[date, float]
) -> tuple[Segment, ...]:
    """Slice the session by player-day and efficiency band given AFK time already used on each day."""
    segs: list[Segment] = []
    offset = 0.0
    for day, secs in day_slices(cfg, start, duration_s):
        used = prior_seconds.get(day, 0.0)
        remaining = secs
        while remaining > 1e-9:
            band = next(
                (b for b in cfg.daily_efficiency_bands if b.from_hours * 3600 <= used < b.to_hours * 3600),
                cfg.daily_efficiency_bands[-1],
            )
            room = max(band.to_hours * 3600 - used, 0.0) or remaining
            take = min(remaining, room)
            segs.append(Segment(start_s=offset, end_s=offset + take, percent=band.percent, day=day))
            offset, used, remaining = offset + take, used + take, remaining - take
    return tuple(segs)


def efficiency_at(segments: tuple[Segment, ...], offset_s: float) -> int:
    for s in segments:
        if s.start_s <= offset_s < s.end_s:
            return s.percent
    return segments[-1].percent if segments else 100


def used_by_day(segments: tuple[Segment, ...], elapsed_s: float) -> dict[date, float]:
    out: dict[date, float] = {}
    for s in segments:
        used = max(0.0, min(s.end_s, elapsed_s) - s.start_s)
        if used > 0:
            out[s.day] = out.get(s.day, 0.0) + used
    return out


def over_level_pct(cfg: AfkBalance, character_level: int, zone_max_level: int) -> float:
    over = character_level - zone_max_level - cfg.over_level.grace_levels
    if over <= 0:
        return 100.0
    return max(cfg.over_level.min_pct, 100.0 - over * cfg.over_level.per_level_pct)


# --------------------------------------------------------------------------- snapshot + resolution
class RiskSnapshot(_S):
    code: str
    xp_loot_percent: int
    enemy_power_percent: int
    death_risk_percent: int
    consumption_percent: int
    rare_bonus_percent: int


class AfkSnapshot(_S):
    """Immutable inputs captured at session start (stored as JSON on the session row)."""

    schema_version: int = 1
    character_id: int
    character_level: int
    character_xp: int
    player: CombatantSnapshot
    strategy: CombatStrategy
    rules: tuple[dict[str, Any], ...]
    boss_rules: tuple[dict[str, Any], ...]
    zone: ZoneBundle
    risk: RiskSnapshot
    combat: CombatConfig
    afk: AfkBalance
    xp_per_unit: float  # XP for one normal-enemy reward unit at 100% (from the progression curve at start)
    over_level_pct: float
    rested_bonus_pct: float = 0
    potions_reserved: int = 0
    pity_start: int = 0
    profession_task: dict[str, Any] | None = None
    segments: tuple[Segment, ...]
    planned_seconds: int
    content_version: int
    build: dict[str, Any] = {}  # human-readable build summary for the UI (class, spec, talents, gear)


class SampleStats(_S):
    fights: int
    win_rate: float
    avg_time_s: float
    avg_damage_frac: float  # net damage taken / max hp
    avg_potions: float


def _sample(snap: AfkSnapshot, seed: int, *, boss: bool, count: int, sim: Callable[..., Any]) -> dict[str, SampleStats]:
    """Full combat simulations grouped by encounter code (+ '*' aggregate)."""
    rules = validate_rules(list(snap.boss_rules if boss else snap.rules))
    enemy_sel = rules_by_code_selector(enemy_rules(snap.zone))
    acc: dict[str, list[tuple[bool, float, float, int]]] = {}
    max_hp = max(snap.player.stats.get("max_hp", 1.0), 1.0)
    for i in range(count):
        fight_seed = derive_seed(seed, "sample", "boss" if boss else "normal", i)
        enc = generate_encounter(
            snap.zone,
            Rng(derive_seed(fight_seed, "encounter")),
            snap.character_level,
            power_percent=snap.risk.enemy_power_percent,
            force_boss=boss,
        )
        strategy = snap.strategy.model_copy(update={"potions": min(snap.potions_reserved, 3)})
        r = sim(
            CombatInput(players=(snap.player,), enemies=enc.enemies, strategy=strategy, seed=fight_seed),
            snap.combat,
            selector=rule_selector(rules),
            enemy_selector=enemy_sel,
        )
        me = r.combatants[0]
        net = max(0.0, me.damage_taken - me.shield_absorbed - me.healing_done) / max_hp
        row = (r.outcome == "win", r.elapsed_s, net, me.potions_used)
        acc.setdefault(enc.code, []).append(row)
        acc.setdefault("*", []).append(row)
    return {
        code: SampleStats(
            fights=len(rows),
            win_rate=sum(w for w, *_ in rows) / len(rows),
            avg_time_s=sum(t for _, t, _, _ in rows) / len(rows),
            avg_damage_frac=sum(d for *_, d, _ in rows) / len(rows),
            avg_potions=sum(p for *_, p in rows) / len(rows),
        )
        for code, rows in acc.items()
    }


def _stats_for(samples: dict[str, SampleStats], code: str) -> SampleStats:
    return samples.get(code) or samples["*"]


def resolve(snap: AfkSnapshot, seed: int, elapsed_s: float, *, sim: Callable[..., Any] = simulate) -> dict[str, Any]:
    cfg = snap.afk
    elapsed_s = max(0.0, min(elapsed_s, float(snap.planned_seconds), float(cfg.max_session_seconds)))
    normal = _sample(snap, seed, boss=False, count=cfg.sample_fights, sim=sim)
    bosses = (
        _sample(snap, seed, boss=True, count=cfg.boss_sample_fights, sim=sim)
        if snap.zone.bosses and cfg.boss_sample_fights
        else {}
    )
    rng = Rng(derive_seed(seed, "walk"))
    risk = snap.risk
    reward_mult = risk.xp_loot_percent / 100 * snap.over_level_pct / 100 * (1 + snap.rested_bonus_pct / 100)
    xp_mult = reward_mult * snap.zone.tier_scaling.xp_pct / 100 * snap.zone.loot_modifiers.get("xp_pct", 100) / 100
    gold_mult = (
        reward_mult * snap.zone.tier_scaling.gold_pct / 100 * snap.zone.loot_modifiers.get("gold_pct", 100) / 100
    )
    death_scale = risk.death_risk_percent / 100
    t = 0.0
    fights = wins = deaths = kills = boss_kills = 0
    xp = gold = 0.0
    potions = 0.0
    eff_weighted = fight_time = 0.0
    pity = snap.pity_start
    drops: dict[tuple[Any, ...], int] = {}
    encounters: dict[str, int] = {}
    bucket = cfg.timeline_bucket_s
    timeline: list[dict[str, float]] = [
        {"xp": 0, "kills": 0, "deaths": 0} for _ in range(max(1, math.ceil(elapsed_s / bucket)))
    ]
    while fights < cfg.max_fights:
        enc = generate_encounter(
            snap.zone,
            Rng(derive_seed(seed, "fight", fights)),
            snap.character_level,
            power_percent=risk.enemy_power_percent,
        )
        stats = _stats_for(bosses, enc.code) if enc.boss and bosses else _stats_for(normal, enc.code)
        if t + stats.avg_time_s > elapsed_s:
            break
        fights += 1
        encounters[enc.code] = encounters.get(enc.code, 0) + 1
        slot = min(int(t // bucket), len(timeline) - 1)
        eff = efficiency_at(snap.segments, t) / 100
        eff_weighted += eff * stats.avg_time_s
        fight_time += stats.avg_time_s
        loss_p = min(1.0, (1 - stats.win_rate) * death_scale)
        potions += stats.avg_potions * risk.consumption_percent / 100
        if rng.chance(loss_p * 100):
            deaths += 1
            timeline[slot]["deaths"] += 1
            t += stats.avg_time_s + cfg.death_recovery_s
            continue
        wins += 1
        n = len(enc.enemies)
        kills += n
        boss_kills += enc.boss
        timeline[slot]["kills"] += n
        gained = enc.reward_pct / 100 * snap.xp_per_unit * xp_mult * eff
        xp += gained
        timeline[slot]["xp"] += gained
        table_code = snap.zone.enemies[enc.code].drop_table if enc.boss else snap.zone.zone_drop_table
        table = snap.zone.drop_tables.get(table_code or "")
        if table is not None:
            forced_rare = pity + 1 >= cfg.pity_threshold_fights
            rolled = roll_drops(
                Rng(derive_seed(seed, "drops", fights)),
                table.rolls,
                table.entries,
                boss=enc.boss,
                rare_bonus_pct=risk.rare_bonus_percent + (1_000_000 if forced_rare else 0),
            )
            got_rare = False
            for d in rolled:
                if d["kind"] == "gold":
                    gold += d["qty"] * gold_mult * eff
                    continue
                if not rng.chance(eff * 100):  # daily efficiency also thins item drops
                    continue
                key = (d["kind"], d.get("ref"), d.get("tier"), d.get("category"), d.get("rarity"))
                drops[key] = drops.get(key, 0) + d["qty"]
                got_rare = got_rare or bool(d.get("rare"))
            pity = 0 if got_rare else pity + 1
        t += stats.avg_time_s + cfg.downtime_base_s + cfg.rest_full_hp_s * min(1.0, stats.avg_damage_frac)
        if t >= elapsed_s:
            break
    gold_int = int(gold)
    death_cost = int(gold_int * min(1.0, deaths * cfg.death_gold_cost_pct / 100))
    active = min(t, elapsed_s)
    result: dict[str, Any] = {
        "elapsed_s": round(elapsed_s, 3),
        "active_s": round(active, 3),
        "fights": fights,
        "wins": wins,
        "deaths": deaths,
        "kills": kills,
        "boss_kills": boss_kills,
        "xp": int(xp),
        "gold": gold_int - death_cost,
        "death_gold_cost": death_cost,
        "durability_loss_pct": round(min(100.0, deaths * cfg.durability_loss_per_death_pct), 2),
        "potions_used": min(snap.potions_reserved, round(potions)),
        "avg_efficiency_pct": round(100 * eff_weighted / fight_time, 2) if fight_time else 0.0,
        "drops": [
            {"kind": k[0], "ref": k[1], "tier": k[2], "category": k[3], "rarity": k[4], "qty": q}
            for k, q in sorted(drops.items(), key=lambda kv: json.dumps(kv[0]))
        ],
        "encounters": dict(sorted(encounters.items())),
        "pity_end": pity,
        "timeline": [{k: round(v, 2) for k, v in b.items()} for b in timeline],
        "samples": {
            "normal": {k: v.model_dump() for k, v in sorted(normal.items())},
            "boss": {k: v.model_dump() for k, v in sorted(bosses.items())},
        },
        "rested_bonus_pct": snap.rested_bonus_pct,
        "over_level_pct": snap.over_level_pct,
    }
    result["hash"] = result_hash(result)
    return result


def result_hash(result: dict[str, Any]) -> str:
    body = {k: v for k, v in result.items() if k != "hash"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def snapshot_hash(snap: AfkSnapshot) -> str:
    """Canonical (key-sorted) hash: stable across JSONB storage, which reorders object keys."""
    body = json.dumps(snap.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(body.encode()).hexdigest()
