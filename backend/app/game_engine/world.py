"""Pure PvE world math: enemy stat scaling, encounter/boss rolls and drop-table rolls (deterministic RNG).

Two separate scaling layers (canonical): per-level `EnemyScaling` (balance config) and per-zone-tier
`TierScaling` (zone tier content). Bosses are distinct templates and flagged `is_boss`."""

from collections.abc import Callable, Sequence
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.game_engine.combat.engine import Actor, Battle
from app.game_engine.combat.models import AbilitySnapshot, CombatantSnapshot
from app.game_engine.combat.rules import RuleSet, rule_selector, validate_rules
from app.game_engine.rng import Rng

ENEMY_STATS = ("max_hp", "attack_power", "armor", "magic_resist", "accuracy", "dodge", "crit_chance", "attack_speed")


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RankMods(_M):
    hp_pct: float = Field(gt=0, le=10_000)
    attack_pct: float = Field(gt=0, le=1_000)
    defense_pct: float = Field(gt=0, le=1_000)


class Sanity(_M):
    """Reference same-level player used only for publish-time 'impossible enemy' warnings."""

    player_hp_base: float = Field(gt=0)
    player_hp_per_level: float = Field(ge=0)
    player_dps_base: float = Field(gt=0)
    player_dps_per_level: float = Field(ge=0)
    max_ttk_s: dict[str, float]  # per rank: normal/elite/boss
    min_player_survival_s: dict[str, float]


class EnemyScaling(_M):
    hp_base: float = Field(ge=1)
    hp_per_level: float = Field(ge=0)
    attack_base: float = Field(ge=0)
    attack_per_level: float = Field(ge=0)
    armor_per_level: float = Field(ge=0)
    magic_resist_per_level: float = Field(ge=0)
    accuracy: float = Field(ge=0, le=200)
    dodge: float = Field(ge=0, le=100)
    crit_chance: float = Field(ge=0, le=100)
    dodge_cap: float = Field(ge=0, le=100)
    ranks: dict[Literal["normal", "elite", "boss"], RankMods]
    archetypes: dict[str, dict[str, float]]  # archetype -> stat -> percent modifier
    max_pack_size: int = Field(ge=1, le=10)
    sanity: Sanity


class TierScaling(_M):
    hp_pct: float = Field(gt=0, le=1000)
    attack_pct: float = Field(gt=0, le=1000)
    defense_pct: float = Field(gt=0, le=1000)
    xp_pct: float = Field(gt=0, le=1000)
    gold_pct: float = Field(gt=0, le=1000)


def enemy_stats(
    cfg: EnemyScaling,
    tier: TierScaling,
    level: int,
    *,
    rank: str,
    archetype: str,
    stat_mods: dict[str, float],
    power_percent: float = 100.0,
) -> dict[str, float]:
    r = cfg.ranks[rank]  # type: ignore[index]
    base = {
        "max_hp": (cfg.hp_base + cfg.hp_per_level * level) * r.hp_pct / 100 * tier.hp_pct / 100,
        "attack_power": (cfg.attack_base + cfg.attack_per_level * level) * r.attack_pct / 100 * tier.attack_pct / 100,
        "armor": cfg.armor_per_level * level * r.defense_pct / 100 * tier.defense_pct / 100,
        "magic_resist": cfg.magic_resist_per_level * level * r.defense_pct / 100 * tier.defense_pct / 100,
        "accuracy": cfg.accuracy,
        "dodge": cfg.dodge,
        "crit_chance": cfg.crit_chance,
        "attack_speed": 100.0,
    }
    mods = {**cfg.archetypes.get(archetype, {})}
    for k, v in stat_mods.items():
        mods[k] = mods.get(k, 0.0) + v
    out = {k: v * (1 + mods.get(k, 0.0) / 100) for k, v in base.items()}
    power = power_percent / 100
    out["max_hp"] *= power
    out["attack_power"] *= power
    out["dodge"] = min(out["dodge"], cfg.dodge_cap)
    out["crit_damage"] = 150.0
    return {k: round(v, 4) for k, v in out.items()}


def boss_effects(phases: Sequence[dict[str, Any]], enrage_after_s: float | None) -> list[dict[str, Any]]:
    """Boss phases → once-per-combat HP thresholds; enrage → time-conditioned damage bonus."""
    out: list[dict[str, Any]] = [
        {
            "effect_type": "THRESHOLD_TRIGGER",
            "params": {
                "condition": {"metric": "self_hp_pct", "op": "lt", "value": p["hp_below_pct"]},
                "effects": p["effects"],
                "once_per_combat": True,
            },
        }
        for p in phases
    ]
    if enrage_after_s:
        out.append(
            {
                "effect_type": "DAMAGE_MULTIPLIER",
                "params": {
                    "percent": 100,
                    "condition": {"metric": "combat_time_s", "op": "gte", "value": enrage_after_s},
                },
            }
        )
    return out


def ability_snapshots(abilities: Sequence[dict[str, Any]]) -> tuple[AbilitySnapshot, ...]:
    return tuple(
        AbilitySnapshot(
            code=a["code"],
            ability_type=a.get("type", "ACTIVE"),
            target_rule=a.get("target", "enemy_single"),
            tags=tuple(a.get("tags", ())),
            cooldown_s=float(a.get("cooldown_s", 0)),
            cast_time_s=float(a.get("cast_time_s", 0)),
            effects=tuple(a["effects"]),
        )
        for a in abilities
    )


def pick_weighted(rng: Rng, pool: Sequence[dict[str, Any]], weight_key: str = "weight") -> dict[str, Any] | None:
    weights = [float(p.get(weight_key, 0)) for p in pool]
    if not pool or sum(weights) <= 0:
        return None
    return pool[rng.weighted_index(weights)]


def roll_pack(rng: Rng, members: Sequence[dict[str, Any]], max_pack: int) -> list[str]:
    codes: list[str] = []
    for m in members:
        codes += [m["enemy_code"]] * rng.randint(int(m["min"]), int(m["max"]))
    return codes[:max_pack] or [members[0]["enemy_code"]]


def roll_drops(
    rng: Rng, rolls: int, entries: Sequence[dict[str, Any]], *, boss: bool, rare_bonus_pct: float = 0
) -> list[dict[str, Any]]:
    """Weighted drop rolls. Each roll picks one eligible entry, then applies its chance; rare_bonus raises the
    chance of rare-or-better entries (risk profile `elite_hunt`)."""
    eligible = [e for e in entries if boss or not e.get("boss_only")]
    out: list[dict[str, Any]] = []
    for _ in range(rolls):
        entry = pick_weighted(rng, eligible)
        if entry is None or entry["kind"] == "nothing":
            continue
        chance = float(entry.get("chance_pct", 100))
        if entry.get("rare"):
            chance = min(100.0, chance * (1 + rare_bonus_pct / 100))
        if not rng.chance(chance):
            continue
        qty = rng.randint(int(entry.get("min_qty", 1)), int(entry.get("max_qty", 1)))
        out.append(
            {**{k: v for k, v in entry.items() if k not in ("weight", "chance_pct", "min_qty", "max_qty")}, "qty": qty}
        )
    return out


def rules_by_code_selector(rules: dict[str, RuleSet]) -> Callable[[Battle, Actor], AbilitySnapshot | None]:
    """Enemy selector: each enemy template's ability profile rules; basic attack otherwise."""
    selectors = {code: rule_selector(rs) for code, rs in rules.items() if rs.rules}

    def select(battle: Battle, actor: Actor) -> AbilitySnapshot | None:
        sel = selectors.get(actor.snap.code)
        return sel(battle, actor) if sel else None

    return select


def sanity_issues(cfg: EnemyScaling, stats: dict[str, float], level: int, rank: str) -> list[str]:
    """Human-readable warnings for enemies that are practically unkillable or instantly lethal."""
    s = cfg.sanity
    issues: list[str] = []
    if stats["max_hp"] <= 0 or stats["attack_power"] < 0:
        issues.append("non-positive hp or negative attack")
    player_dps = s.player_dps_base + s.player_dps_per_level * level
    player_hp = s.player_hp_base + s.player_hp_per_level * level
    ttk = stats["max_hp"] / player_dps
    if ttk > s.max_ttk_s[rank]:
        issues.append(f"estimated time to kill {ttk:.0f}s > {s.max_ttk_s[rank]:.0f}s")
    enemy_dps = stats["attack_power"] / 2.0 * stats["attack_speed"] / 100
    if enemy_dps > 0 and player_hp / enemy_dps < s.min_player_survival_s[rank]:
        issues.append(f"estimated player survival {player_hp / enemy_dps:.1f}s < {s.min_player_survival_s[rank]:.0f}s")
    if stats["dodge"] >= cfg.dodge_cap:
        issues.append("dodge at cap")
    return issues


def enemy_snapshot(
    sid: str,
    code: str,
    level: int,
    stats: dict[str, float],
    *,
    damage_type: str,
    effects: Sequence[dict[str, Any]] = (),
    abilities: tuple[AbilitySnapshot, ...] = (),
    boss: bool = False,
    elite: bool = False,
    tags: Sequence[str] = (),
) -> CombatantSnapshot:
    return CombatantSnapshot(
        id=sid,
        code=code,
        side="enemies",
        level=level,
        stats=stats,
        effects=tuple(effects),
        abilities=abilities,
        base_damage_type=damage_type,
        is_boss=boss,
        is_elite=elite,
        tags=tuple(tags),
    )


# --------------------------------------------------------------------------- immutable zone bundle
class EnemyDef(_M):
    code: str
    rank: Literal["normal", "elite", "boss"]
    archetype: str
    damage_type: str
    stat_mods: dict[str, float] = {}
    effects: tuple[dict[str, Any], ...] = ()
    abilities: tuple[dict[str, Any], ...] = ()
    rules: tuple[dict[str, Any], ...] = ()
    tags: tuple[str, ...] = ()
    reward_pct: int = 100
    adds: tuple[dict[str, Any], ...] = ()
    drop_table: str | None = None


class DropTableDef(_M):
    rolls: int
    entries: tuple[dict[str, Any], ...]


class ZoneBundle(_M):
    """Everything needed to generate this zone's fights offline. Stored in AFK session snapshots so live
    content edits never change an old session."""

    code: str
    tier: int
    min_level: int
    max_level: int
    tier_scaling: TierScaling
    scaling: EnemyScaling
    encounters: tuple[dict[str, Any], ...]  # {code, weight, members}
    bosses: tuple[dict[str, Any], ...]  # {code, weight}
    boss_chance_pct: float
    enemies: dict[str, EnemyDef]
    drop_tables: dict[str, DropTableDef]
    zone_drop_table: str | None
    loot_modifiers: dict[str, float]
    content_version: int = 0


class GeneratedEncounter(_M):
    code: str
    boss: bool
    level: int
    enemies: tuple[CombatantSnapshot, ...]
    reward_pct: int  # sum of enemy reward percents (100 = one normal enemy)


def encounter_level(bundle: ZoneBundle, character_level: int) -> int:
    return max(bundle.min_level, min(bundle.max_level, character_level))


def _snap(bundle: ZoneBundle, d: EnemyDef, sid: str, level: int, power: float) -> CombatantSnapshot:
    stats = enemy_stats(
        bundle.scaling,
        bundle.tier_scaling,
        level,
        rank=d.rank,
        archetype=d.archetype,
        stat_mods=d.stat_mods,
        power_percent=power,
    )
    return enemy_snapshot(
        sid,
        d.code,
        level,
        stats,
        damage_type=d.damage_type,
        effects=d.effects,
        abilities=ability_snapshots(d.abilities),
        boss=d.rank == "boss",
        elite=d.rank == "elite",
        tags=d.tags,
    )


def generate_encounter(
    bundle: ZoneBundle, rng: Rng, character_level: int, *, power_percent: float = 100.0, force_boss: bool = False
) -> GeneratedEncounter:
    level = encounter_level(bundle, character_level)
    if bundle.bosses and (force_boss or rng.chance(bundle.boss_chance_pct)):
        pick = pick_weighted(rng, bundle.bosses)
        assert pick is not None
        boss = bundle.enemies[pick["code"]]
        snaps = [_snap(bundle, boss, "b0", level, power_percent)]
        reward = boss.reward_pct
        for add in boss.adds:
            d = bundle.enemies[add["enemy_code"]]
            for _ in range(int(add["count"])):
                snaps.append(_snap(bundle, d, f"e{len(snaps)}", level, power_percent))
                reward += d.reward_pct
        return GeneratedEncounter(code=boss.code, boss=True, level=level, enemies=tuple(snaps), reward_pct=reward)
    enc = pick_weighted(rng, bundle.encounters)
    assert enc is not None
    codes = roll_pack(rng, enc["members"], bundle.scaling.max_pack_size)
    snaps = [_snap(bundle, bundle.enemies[c], f"e{i}", level, power_percent) for i, c in enumerate(codes)]
    reward = sum(bundle.enemies[c].reward_pct for c in codes)
    return GeneratedEncounter(code=enc["code"], boss=False, level=level, enemies=tuple(snaps), reward_pct=reward)


def enemy_rules(bundle: ZoneBundle) -> dict[str, RuleSet]:
    return {code: validate_rules(list(d.rules)) for code, d in bundle.enemies.items() if d.rules}
