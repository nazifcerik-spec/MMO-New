"""Immutable combat inputs/outputs (JSON-serializable; stored inside AFK snapshots for replay)."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ResourceSnapshot(_M):
    code: str
    max: float = Field(gt=0)
    start: float = Field(ge=0)
    regen_per_s: float = Field(ge=0)
    decay_per_s: float = Field(ge=0)


class AbilitySnapshot(_M):
    code: str
    ability_type: Literal["ACTIVE", "ULTIMATE", "STANCE", "PASSIVE", "AURA", "PROC"]
    target_rule: str = "enemy_single"
    tags: tuple[str, ...] = ()
    cost_resource: str | None = None
    cost_amount: float = 0
    cooldown_s: float = 0
    cast_time_s: float = 0
    effects: tuple[dict[str, Any], ...] = ()


class CombatantSnapshot(_M):
    id: str
    code: str
    side: Literal["players", "enemies"]
    level: int = Field(ge=1, le=1000)
    stats: dict[str, float]
    resources: tuple[ResourceSnapshot, ...] = ()
    primary_resource: str | None = None
    effects: tuple[dict[str, Any], ...] = ()  # runtime (non-static) effects: triggers, conditional modifiers
    abilities: tuple[AbilitySnapshot, ...] = ()
    weapon_family: str | None = None
    power_stat: Literal["attack_power", "spell_power"] = "attack_power"
    base_damage_type: str = "physical"
    base_attack_interval_s: float = Field(default=2.0, gt=0.1, le=10)
    is_boss: bool = False
    is_elite: bool = False
    role: Literal["tank", "dps", "healer", "support"] = "dps"
    tags: tuple[str, ...] = ()


class StanceDef(_M):
    damage_percent: float = 0
    damage_taken_percent: float = 0
    resource_cost_percent: float = 0
    attack_speed_percent: float = 0


class CombatStrategy(_M):
    mode: Literal["PASSIVE_ONLY", "ACTIVE_TACTICS", "HYBRID"] = "HYBRID"
    stance: str = "efficient"
    target_priority: Literal["first", "lowest_hp", "highest_hp", "elite_first", "boss_first", "healer_first"] = (
        "lowest_hp"
    )
    potion_threshold_pct: float = Field(default=40, ge=0, le=100)
    potions: int = Field(default=0, ge=0, le=1000)
    potion_heal_pct: float = Field(default=35, ge=0, le=100)
    potion_cooldown_s: float = Field(default=15, ge=0, le=600)
    tactics: tuple[dict[str, Any], ...] = ()  # Active Tactics rules (validated by the tactics DSL)
    use_abilities: bool = True


class CombatConfig(_M):
    """Balance values for combat math (published `combat` balance config)."""

    max_duration_s: float = Field(default=180, gt=0, le=3600)
    armor_k: float = Field(default=50, gt=0)
    armor_k_base: float = Field(default=200, ge=0)
    max_mitigation_pct: float = Field(default=75, gt=0, le=95)
    max_penetration_pct: float = Field(default=50, ge=0, le=100)
    damage_variance_pct: float = Field(default=5, ge=0, le=50)
    min_hit_pct: float = Field(default=60, ge=0, le=100)
    level_diff_hit_pct: float = Field(default=1.0, ge=0, le=10)
    crit_cap_pct: float = Field(default=75, ge=0, le=100)
    max_damage_reduction_pct: float = Field(default=75, ge=0, le=95)
    min_attack_interval_s: float = Field(default=0.4, gt=0)
    gcd_s: float = Field(default=1.0, ge=0)
    regen_tick_s: float = Field(default=1.0, gt=0)
    threat_damage_factor: float = Field(default=1.0, ge=0)
    threat_heal_factor: float = Field(default=0.5, ge=0)
    lifesteal_cap_pct: float = Field(default=30, ge=0, le=100)
    log_limit: int = Field(default=120, ge=0, le=5000)
    coefficients: dict[str, dict[str, float]] = Field(
        default_factory=lambda: {
            "pve": {"damage": 1.0, "healing": 1.0, "cc_duration": 1.0},
            "pvp": {"damage": 0.7, "healing": 0.7, "cc_duration": 0.5},
        }
    )
    stances: dict[str, StanceDef] = Field(default_factory=dict)


class CombatInput(_M):
    players: tuple[CombatantSnapshot, ...] = Field(min_length=1)
    enemies: tuple[CombatantSnapshot, ...] = Field(min_length=1)
    strategy: CombatStrategy = CombatStrategy()
    seed: int = Field(ge=0, lt=2**64)
    context: Literal["pve", "pvp"] = "pve"
    content_version: int = 0


class CombatantResult(_M):
    id: str
    alive: bool
    hp_end: float
    damage_dealt: float
    damage_taken: float
    healing_done: float
    overhealing: float
    shield_absorbed: float
    shield_granted: float
    resource_spent: dict[str, float]
    hits: int
    crits: int
    dodges: int
    blocks: int
    kills: int
    abilities_used: dict[str, int]
    procs: dict[str, int]
    potions_used: int
    buff_uptime_s: float
    debuffs_applied: int
    ally_buff_uptime_s: float = 0.0
    damage_prevented: float = 0.0


class CombatResult(_M):
    outcome: Literal["win", "loss", "timeout"]
    elapsed_s: float
    seed: int
    rng_draws: int
    events_processed: int
    combatants: tuple[CombatantResult, ...]
    killed_enemy_ids: tuple[str, ...]
    log: tuple[dict[str, Any], ...]
    log_truncated: bool
    content_version: int
