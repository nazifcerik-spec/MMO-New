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
from app.game_engine.loot import LootConfig, luck_bonus, roll_table
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
    loot_modifier_caps: dict[str, float] = Field(default_factory=dict)  # LOOT_MODIFIER totals are capped per scope

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
    loot: LootConfig | None = None  # Phase 19; None for older sessions (legacy drop rolls)
    # Phase 21 group AFK: allies frozen at start (own snapshot per member), shared fight seed, personal loot salt.
    party: tuple[CombatantSnapshot, ...] = ()
    group_id: str | None = None
    loot_salt: int = 0
    party_power_pct_per_member: float = 0.0
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


def drop_seed(seed: int, fight: int, salt: int) -> int:
    """Group members share the fight timeline but roll personal loot (salted); salt 0 keeps solo/legacy rolls."""
    return derive_seed(seed, "drops", fight, salt) if salt else derive_seed(seed, "drops", fight)


def enemy_power_pct(snap: AfkSnapshot) -> float:
    """Encounters scale with party size (config recorded in the snapshot)."""
    return snap.risk.enemy_power_percent * (1 + len(snap.party) * snap.party_power_pct_per_member / 100)


CONTRIB_KEYS = ("damage", "healing", "shield_granted", "damage_prevented", "ally_buff_uptime_s", "debuffs_applied")


def _sample(
    snap: AfkSnapshot,
    seed: int,
    *,
    boss: bool,
    count: int,
    sim: Callable[..., Any],
    contrib: dict[str, float] | None = None,
) -> dict[str, SampleStats]:
    """Full combat simulations grouped by encounter code (+ '*' aggregate). With a party, every fight includes the
    frozen ally snapshots; `contrib` (if given) accumulates this member's support metrics, including the party
    DPS gained versus the same fight without this member (counterfactual)."""
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
            power_percent=enemy_power_pct(snap),
            force_boss=boss,
        )
        strategy = snap.strategy.model_copy(update={"potions": min(snap.potions_reserved, 3)})
        r = sim(
            CombatInput(players=(snap.player, *snap.party), enemies=enc.enemies, strategy=strategy, seed=fight_seed),
            snap.combat,
            selector=rule_selector(rules),
            enemy_selector=enemy_sel,
        )
        me = r.combatants[0]
        net = max(0.0, me.damage_taken - me.shield_absorbed - me.healing_done) / max_hp
        row = (r.outcome == "win", r.elapsed_s, net, me.potions_used)
        acc.setdefault(enc.code, []).append(row)
        acc.setdefault("*", []).append(row)
        if contrib is not None and snap.party:
            n_party = len(snap.party) + 1
            allies_with = sum(c.damage_dealt for c in r.combatants[1:n_party]) / max(r.elapsed_s, 1.0)
            without = sim(
                CombatInput(players=snap.party, enemies=enc.enemies, strategy=strategy, seed=fight_seed),
                snap.combat,
                selector=rule_selector(rules),
                enemy_selector=enemy_sel,
            )
            allies_without = sum(c.damage_dealt for c in without.combatants[: n_party - 1]) / max(
                without.elapsed_s, 1.0
            )
            for k, v in (
                ("damage", me.damage_dealt),
                ("healing", me.healing_done),
                ("shield_granted", me.shield_granted),
                ("damage_prevented", me.damage_prevented),
                ("ally_buff_uptime_s", me.ally_buff_uptime_s),
                ("debuffs_applied", float(me.debuffs_applied)),
                ("party_dps_gained", allies_with - allies_without),
                ("fights", 1.0),
            ):
                contrib[k] = contrib.get(k, 0.0) + v
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


def loot_modifiers(snap: AfkSnapshot) -> dict[str, float]:
    """LOOT_MODIFIER totals from the player's effects (gear/gadgets/race), capped per scope by config."""
    out: dict[str, float] = {}
    for e in snap.player.effects:
        if e.get("effect_type") == "LOOT_MODIFIER":
            scope = e["params"]["scope"]
            out[scope] = out.get(scope, 0.0) + float(e["params"]["percent"])
    return {k: min(v, snap.afk.loot_modifier_caps.get(k, v)) for k, v in sorted(out.items())}


def _contribution(snap: AfkSnapshot, c: dict[str, float]) -> dict[str, Any]:
    n = max(c.get("fights", 0.0), 1.0)
    per = {k: round(c.get(k, 0.0) / n, 3) for k in (*CONTRIB_KEYS, "party_dps_gained")}
    return {"role": snap.player.role, "party_size": len(snap.party) + 1, "per_fight": per, "sample_fights": int(n)}


def _empty_result(snap: AfkSnapshot, elapsed_s: float) -> dict[str, Any]:
    """Profession-task sessions gather instead of fighting: no combat rewards, no deaths."""
    result: dict[str, Any] = {
        "elapsed_s": round(elapsed_s, 3),
        "active_s": round(elapsed_s, 3),
        "fights": 0,
        "wins": 0,
        "deaths": 0,
        "kills": 0,
        "boss_kills": 0,
        "xp": 0,
        "gold": 0,
        "death_gold_cost": 0,
        "durability_loss_pct": 0.0,
        "potions_used": 0,
        "avg_efficiency_pct": 0.0,
        "drops": [],
        "encounters": {},
        "pity_end": snap.pity_start,
        "timeline": [],
        "samples": {"normal": {}, "boss": {}},
        "rested_bonus_pct": snap.rested_bonus_pct,
        "over_level_pct": snap.over_level_pct,
        "mode": "profession",
    }
    result["hash"] = result_hash(result)
    return result


def resolve(snap: AfkSnapshot, seed: int, elapsed_s: float, *, sim: Callable[..., Any] = simulate) -> dict[str, Any]:
    cfg = snap.afk
    elapsed_s = max(0.0, min(elapsed_s, float(snap.planned_seconds), float(cfg.max_session_seconds)))
    if snap.profession_task is not None:
        return _empty_result(snap, elapsed_s)
    mods = loot_modifiers(snap)
    contrib: dict[str, float] = {}
    normal = _sample(snap, seed, boss=False, count=cfg.sample_fights, sim=sim, contrib=contrib)
    bosses = (
        _sample(snap, seed, boss=True, count=cfg.boss_sample_fights, sim=sim)
        if snap.zone.bosses and cfg.boss_sample_fights
        else {}
    )
    rng = Rng(derive_seed(seed, "walk"))
    risk = snap.risk
    reward_mult = risk.xp_loot_percent / 100 * snap.over_level_pct / 100 * (1 + snap.rested_bonus_pct / 100)
    xp_mult = reward_mult * snap.zone.tier_scaling.xp_pct / 100 * snap.zone.loot_modifiers.get("xp_pct", 100) / 100
    xp_mult *= 1 + mods.get("xp", 0) / 100
    gold_mult = (
        reward_mult * snap.zone.tier_scaling.gold_pct / 100 * snap.zone.loot_modifiers.get("gold_pct", 100) / 100
    )
    gold_mult *= 1 + mods.get("gold", 0) / 100
    drop_keep = 1 + mods.get("drop_rate", 0) / 100
    luck = luck_bonus(snap.loot, snap.player.stats.get("LUK", 0)) if snap.loot is not None else 0.0
    rare_bonus = risk.rare_bonus_percent + mods.get("rare_chance", 0) + luck
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
            power_percent=enemy_power_pct(snap),
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
            if snap.loot is not None:
                forced_rare = snap.loot.pity.enabled and pity + 1 >= snap.loot.pity.threshold_fights
                rolled = roll_table(
                    snap.loot,
                    Rng(drop_seed(seed, fights, snap.loot_salt)),
                    table.rolls,
                    table.entries,
                    {"boss": enc.boss, "zone_code": snap.zone.code, "zone_tags": snap.zone.tags,
                     "level": snap.character_level},
                    rare_bonus_pct=rare_bonus,
                    force_rare=forced_rare,
                )  # fmt: skip
            else:
                forced_rare = pity + 1 >= cfg.pity_threshold_fights
                rolled = roll_drops(
                    Rng(derive_seed(seed, "drops", fights)),
                    table.rolls,
                    table.entries,
                    boss=enc.boss,
                    rare_bonus_pct=risk.rare_bonus_percent
                    + mods.get("rare_chance", 0)
                    + (1_000_000 if forced_rare else 0),
                )
            got_rare = False
            for d in rolled:
                if d["kind"] == "gold":
                    gold += d["qty"] * gold_mult * eff
                    continue
                if not rng.chance(min(100.0, eff * 100 * drop_keep)):  # efficiency thins drops; drop_rate helps
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
        "luck_bonus_pct": luck,
        **({"contribution": _contribution(snap, contrib)} if snap.party else {}),
        "timeline": [{k: round(v, 2) for k, v in b.items()} for b in timeline],
        "samples": {
            "normal": {k: v.model_dump() for k, v in sorted(normal.items())},
            "boss": {k: v.model_dump() for k, v in sorted(bosses.items())},
        },
        "rested_bonus_pct": snap.rested_bonus_pct,
        "over_level_pct": snap.over_level_pct,
        "loot_modifiers": mods,
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
