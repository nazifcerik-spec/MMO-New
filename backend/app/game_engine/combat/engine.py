"""Deterministic, HTTP-free combat engine (next-event stepping; no per-millisecond loop).

Inputs are immutable snapshots (`CombatInput`); the same input + seed always yields the same `CombatResult`.
Static stat effects are already baked into snapshot stats; this engine resolves the dynamic parts of the
effect DSL: triggers/procs, thresholds, every-N-hits, stacks, timed buffs/debuffs, shields, DoT/HoT, auras,
scaling bonuses, cooldown/resource-cost modifiers, threat and death. The same core serves passive-only and
Active Tactics combat: an injectable `ActionSelector` decides whether an actor uses an ability or attacks.
"""

import heapq
import itertools
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any

from app.game_engine.combat.models import (
    AbilitySnapshot,
    CombatantResult,
    CombatantSnapshot,
    CombatConfig,
    CombatInput,
    CombatResult,
)
from app.game_engine.rng import Rng

INSTANT_TYPES = frozenset(
    {
        "DAMAGE",
        "HEAL",
        "SHIELD",
        "RESOURCE_GAIN",
        "DOT",
        "HOT",
        "DEBUFF",
        "BUFF",
        "STACK_GAIN",
        "EVERY_N_HITS",
        "PROC_CHANCE",
    }
)
NON_COMBAT_TYPES = frozenset({"LOOT_MODIFIER", "PROGRESSION_MODIFIER", "PROFESSION_YIELD_MOD", "SOLO_ACCORD"})
PHYSICAL = "physical"
TRUE_DAMAGE = "true"


@dataclass(slots=True)
class Timed:
    """A timed modifier bundle (buff/debuff) living on an actor."""

    key: str
    effects: tuple[dict[str, Any], ...]
    expires_at: float
    stacks: int
    max_stacks: int
    source_id: str
    is_debuff: bool
    kind: str | None = None
    percent: float = 0.0


@dataclass(slots=True)
class Periodic:
    key: str
    source_id: str
    target_id: str
    per_tick: float
    tick_s: float
    expires_at: float
    stacks: int
    max_stacks: int
    heal: bool
    damage_type: str


@dataclass
class Actor:
    snap: CombatantSnapshot
    index: int
    hp: float = 0.0
    max_hp: float = 1.0
    alive: bool = True
    resources: dict[str, float] = field(default_factory=dict)
    res_max: dict[str, float] = field(default_factory=dict)
    permanent: list[dict[str, Any]] = field(default_factory=list)
    thresholds: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    procs: dict[str, list[tuple[str, dict[str, Any]]]] = field(default_factory=dict)
    every_n: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    party_auras: list[dict[str, Any]] = field(default_factory=list)
    timed: list[Timed] = field(default_factory=list)
    stacks: dict[str, int] = field(default_factory=dict)
    stack_defs: dict[str, tuple[int, tuple[dict[str, Any], ...]]] = field(default_factory=dict)
    counters: dict[str, int] = field(default_factory=dict)
    icd_ready: dict[str, float] = field(default_factory=dict)
    threshold_state: dict[str, bool] = field(default_factory=dict)
    threshold_used: set[str] = field(default_factory=set)
    cooldown_ready: dict[str, float] = field(default_factory=dict)
    shields: list[list[float]] = field(default_factory=list)  # [amount, expires_at]
    threat: dict[str, float] = field(default_factory=dict)
    frozen_until: float = 0.0
    hit_count: int = 0
    potions_left: int = 0
    potion_ready_at: float = 0.0
    # result counters
    damage_dealt: float = 0.0
    damage_taken: float = 0.0
    healing_done: float = 0.0
    overhealing: float = 0.0
    shield_absorbed: float = 0.0
    shield_granted: float = 0.0
    resource_spent: dict[str, float] = field(default_factory=dict)
    hits: int = 0
    crits: int = 0
    dodges: int = 0
    blocks: int = 0
    kills: int = 0
    abilities_used: dict[str, int] = field(default_factory=dict)
    procs_fired: dict[str, int] = field(default_factory=dict)
    potions_used: int = 0
    buff_uptime: float = 0.0
    debuffs_applied: int = 0

    @property
    def id(self) -> str:
        return self.snap.id

    @property
    def side(self) -> str:
        return self.snap.side


ActionSelector = Callable[["Battle", Actor], AbilitySnapshot | None]


def passive_only_selector(_battle: "Battle", _actor: Actor) -> AbilitySnapshot | None:
    return None


class Battle:
    def __init__(
        self,
        data: CombatInput,
        cfg: CombatConfig,
        selector: ActionSelector | None = None,
        enemy_selector: ActionSelector | None = None,
    ) -> None:
        self.data = data
        self.cfg = cfg
        self.rng = Rng(data.seed)
        self.proc_depth = 0  # procs cannot trigger further procs (prevents unbounded chains)
        self.now = 0.0
        self.coeff = cfg.coefficients.get(data.context, {"damage": 1.0, "healing": 1.0, "cc_duration": 1.0})
        self.selector = selector or passive_only_selector
        self.enemy_selector = enemy_selector or passive_only_selector
        self.stance = cfg.stances.get(data.strategy.stance)
        self.actors: list[Actor] = []
        for i, snap in enumerate((*data.players, *data.enemies)):
            self.actors.append(self._init_actor(snap, i))
        self.by_id = {a.id: a for a in self.actors}
        if len(self.by_id) != len(self.actors):
            raise ValueError("duplicate combatant ids")
        self.queue: list[tuple[float, int, str, str]] = []
        self.seq = itertools.count()
        self.periodics: dict[str, Periodic] = {}
        self.log: list[dict[str, Any]] = []
        self.log_truncated = False
        self.events = 0
        self.targets: dict[str, str] = {}

    # ------------------------------------------------------------------ setup
    def _init_actor(self, snap: CombatantSnapshot, index: int) -> Actor:
        a = Actor(snap=snap, index=index)
        a.max_hp = max(1.0, snap.stats.get("max_hp", 1.0))
        a.hp = a.max_hp
        for r in snap.resources:
            a.resources[r.code] = r.start
            a.res_max[r.code] = r.max
        if snap.side == "players":
            a.potions_left = self.data.strategy.potions
        for i, eff in enumerate(snap.effects):
            self._register(a, eff, f"{snap.id}:e{i}")
        return a

    def _register(self, a: Actor, eff: dict[str, Any], key: str) -> None:
        et, p = eff["effect_type"], eff.get("params", {})
        if et in NON_COMBAT_TYPES:
            return
        if et == "PROC_CHANCE":
            a.procs.setdefault(p.get("trigger", "on_hit"), []).append((key, p))
        elif et == "THRESHOLD_TRIGGER":
            a.thresholds.append((key, p))
        elif et == "EVERY_N_HITS":
            a.every_n.append((key, p))
        elif et == "AURA":
            if p.get("scope", "party") == "party":
                a.party_auras.extend(p["effects"])
            else:
                a.permanent.extend(p["effects"])
        elif et == "STACK_GAIN":
            a.stack_defs[p["stack_code"]] = (int(p.get("max_stacks", 5)), tuple(p.get("per_stack", ())))
        elif et == "WEAPON_FAMILY_BONUS":
            if a.snap.weapon_family in p.get("families", []):
                for j, nested in enumerate(p["effects"]):
                    self._register(a, nested, f"{key}.w{j}")
        elif et in ("STAT_FLAT", "STAT_PERCENT"):
            # Static stats are pre-baked into the snapshot; listed runtime stat effects stay as modifiers.
            a.permanent.append(eff)
        elif et in INSTANT_TYPES:
            return  # instant effects only make sense inside triggers/abilities
        else:
            a.permanent.append(eff)

    # ------------------------------------------------------------------ queue/log
    def push(self, t: float, kind: str, ref: str) -> None:
        heapq.heappush(self.queue, (round(t, 6), next(self.seq), kind, ref))

    def emit(self, event_type: str, **data: Any) -> None:
        if len(self.log) < self.cfg.log_limit:
            self.log.append({"t": round(self.now, 3), "event_type": event_type, **data})
        else:
            self.log_truncated = True

    # ------------------------------------------------------------------ queries
    def allies(self, a: Actor) -> list[Actor]:
        return [x for x in self.actors if x.side == a.side and x.alive]

    def foes(self, a: Actor) -> list[Actor]:
        return [x for x in self.actors if x.side != a.side and x.alive]

    def hp_pct(self, a: Actor) -> float:
        return 100.0 * a.hp / a.max_hp

    def resource_pct(self, a: Actor) -> float:
        code = a.snap.primary_resource
        if not code or code not in a.resources:
            return 0.0
        return 100.0 * a.resources[code] / max(1e-9, self.res_cap(a, code))

    def res_cap(self, a: Actor, code: str) -> float:
        extra = sum(
            p.get("amount", 0) * n
            for et, p, n in self.mods(a, thresholds=False)
            if et == "STACK_CAP_MOD" and p.get("stack_code") == code
        )
        return float(a.res_max.get(code, 0.0) + extra)

    def stack_cap(self, a: Actor, code: str) -> int:
        base = a.stack_defs.get(code, (5, ()))[0]
        extra = sum(
            int(p.get("amount", 0)) * n
            for et, p, n in self.mods(a, thresholds=False)
            if et == "STACK_CAP_MOD" and p.get("stack_code") == code
        )
        return max(1, base + extra)

    def metric(self, a: Actor, target: Actor | None, name: str, stack_code: str | None = None) -> float:
        if name == "self_hp_pct":
            return self.hp_pct(a)
        if name == "missing_hp_pct":
            return 100.0 - self.hp_pct(a)
        if name == "self_resource_pct":
            return self.resource_pct(a)
        if name == "target_hp_pct":
            return self.hp_pct(target) if target else 100.0
        if name == "enemy_count":
            return float(len(self.foes(a)))
        if name == "target_debuff_count":
            return float(sum(1 for t in target.timed if t.is_debuff and t.expires_at > self.now)) if target else 0.0
        if name == "self_buff_count":
            return float(sum(1 for t in a.timed if not t.is_debuff and t.expires_at > self.now))
        if name == "combo_count":
            return float(a.stacks.get("combo", 0))
        if name == "stack_count":
            return float(a.stacks.get(stack_code or "", 0))
        if name == "hit_index":
            return float(a.hit_count + 1)
        if name == "combat_time_s":
            return self.now
        if name == "active_hot_count":
            return float(
                sum(1 for p in self.periodics.values() if p.heal and p.source_id == a.id and p.expires_at > self.now)
            )
        if name == "party_size":
            return float(len([x for x in self.actors if x.side == a.side]))
        return 0.0

    def check(self, a: Actor, target: Actor | None, cond: dict[str, Any] | None) -> bool:
        if not cond:
            return True
        value = self.metric(a, target, cond["metric"], cond.get("stack_code"))
        op, ref = cond["op"], float(cond["value"])
        return {"lt": value < ref, "lte": value <= ref, "gt": value > ref, "gte": value >= ref, "eq": value == ref}[op]

    def mods(
        self, a: Actor, target: Actor | None = None, *, thresholds: bool = True
    ) -> Iterator[tuple[str, dict[str, Any], int]]:
        """All currently active modifier effects on `a` as (effect_type, params, multiplier)."""
        for e in a.permanent:
            yield e["effect_type"], e["params"], 1
        for ally in self.actors:
            if ally.side == a.side and ally.alive:
                for e in ally.party_auras:
                    yield e["effect_type"], e["params"], 1
                for _key, p in ally.thresholds if thresholds else ():
                    if (ally is a or self._has_party_aura(p)) and self.check(ally, target, p["condition"]):
                        for e in p["effects"]:
                            if e["effect_type"] == "AURA":
                                for inner in e["params"]["effects"]:
                                    yield inner["effect_type"], inner["params"], 1
                            elif ally is a and e["effect_type"] not in INSTANT_TYPES:
                                yield e["effect_type"], e["params"], 1
        for t in a.timed:
            if t.expires_at > self.now:
                for e in t.effects:
                    yield e["effect_type"], e["params"], t.stacks
        for code, n in a.stacks.items():
            if n > 0 and code in a.stack_defs:
                for e in a.stack_defs[code][1]:
                    yield e["effect_type"], e["params"], n

    @staticmethod
    def _has_party_aura(p: dict[str, Any]) -> bool:
        return any(e["effect_type"] == "AURA" and e["params"].get("scope", "party") == "party" for e in p["effects"])

    def stat(self, a: Actor, name: str) -> float:
        base = a.snap.stats.get(name, 0.0)
        flat = pct = 0.0
        for et, p, n in self.mods(a):
            if p.get("stat") == name:
                if et == "STAT_FLAT":
                    flat += p["amount"] * n
                elif et == "STAT_PERCENT":
                    pct += p["percent"] * n
        for t in a.timed:
            if t.is_debuff and t.expires_at > self.now:
                if t.kind == "slow" and name == "attack_speed":
                    pct -= t.percent * t.stacks
                if t.kind == "stat" and t.effects and t.effects[0].get("stat") == name:
                    pct -= t.percent * t.stacks
        return (base + flat) * (1 + pct / 100.0)

    def scaling(self, a: Actor, target: Actor | None, applies_to: str) -> float:
        total = 0.0
        for et, p, n in self.mods(a, target):
            if et == "SCALING_BONUS" and p.get("applies_to", "damage") == applies_to:
                steps = int(self.metric(a, target, p["metric"], p.get("stack_code")) // p["step"])
                total += min(p["max_percent"], steps * p["percent_per_step"]) * n
        return total

    def damage_bonus(self, a: Actor, target: Actor, dtype: str) -> float:
        total = self.scaling(a, target, "damage")
        for et, p, n in self.mods(a, target):
            if et != "DAMAGE_MULTIPLIER":
                continue
            if p.get("damage_type") not in (None, dtype):
                continue
            tag = p.get("target_tag")
            if (tag == "boss" and not target.snap.is_boss) or (tag == "elite" and not target.snap.is_elite):
                continue
            if not self.check(a, target, p.get("condition")):
                continue
            total += p["percent"] * n
        return total

    def damage_reduction(self, a: Actor) -> float:
        total = self.scaling(a, None, "damage_reduction")
        for et, p, n in self.mods(a):
            if et == "DAMAGE_REDUCTION" and self.check(a, None, p.get("condition")):
                total += p["percent"] * n
        return min(total, self.cfg.max_damage_reduction_pct)

    def debuff_percent(self, a: Actor, kind: str) -> float:
        return sum(t.percent * t.stacks for t in a.timed if t.is_debuff and t.kind == kind and t.expires_at > self.now)

    def heal_bonus(self, a: Actor, target: Actor, scope: str) -> float:
        total = self.scaling(a, target, "healing")
        for et, p, n in self.mods(a, target):
            if (
                et == "HEAL_MULTIPLIER"
                and p.get("scope", "outgoing") in ("outgoing", scope)
                and self.check(a, target, p.get("condition"))
            ):
                total += p["percent"] * n
        return total

    def cooldown_mods(self, a: Actor, tags: tuple[str, ...]) -> tuple[float, float]:
        pct = no_cd = 0.0
        for et, p, n in self.mods(a):
            if et == "COOLDOWN_MOD" and (p.get("ability_tag") is None or p.get("ability_tag") in tags):
                pct += p.get("percent", 0) * n
                no_cd += p.get("chance_no_cooldown_percent", 0) * n
        return pct, no_cd

    def cost_mod(self, a: Actor, resource: str) -> float:
        return float(
            sum(
                p["percent"] * n
                for et, p, n in self.mods(a)
                if et == "RESOURCE_COST_MOD" and p.get("resource") == resource
            )
        )

    # ------------------------------------------------------------------ targeting
    def pick_target(self, a: Actor) -> Actor | None:
        foes = self.foes(a)
        if not foes:
            return None
        if a.side == "enemies":
            best = max(foes, key=lambda f: (a.threat.get(f.id, 0.0), -f.index))
            return best
        current = self.by_id.get(self.targets.get(a.id, ""))
        if current and current.alive:
            return current
        prio = self.data.strategy.target_priority
        if prio == "lowest_hp":
            choice = min(foes, key=lambda f: (f.hp, f.index))
        elif prio == "highest_hp":
            choice = max(foes, key=lambda f: (f.hp, -f.index))
        elif prio == "boss_first":
            choice = min(foes, key=lambda f: (not f.snap.is_boss, f.index))
        elif prio == "elite_first":
            choice = min(foes, key=lambda f: (not (f.snap.is_elite or f.snap.is_boss), f.index))
        elif prio == "healer_first":
            choice = min(foes, key=lambda f: (f.snap.role != "healer", f.index))
        else:
            choice = foes[0]
        self.targets[a.id] = choice.id
        return choice

    def lowest_ally(self, a: Actor) -> Actor:
        return min(self.allies(a), key=lambda x: (self.hp_pct(x), x.index))

    # ------------------------------------------------------------------ core actions
    def deal_damage(
        self,
        src: Actor,
        tgt: Actor,
        pct: float,
        dtype: str,
        *,
        source: str,
        guaranteed_crit: bool = False,
        armor_ignore: float = 0.0,
        periodic: bool = False,
        flat: float | None = None,
    ) -> float:
        if not tgt.alive or (not src.alive and not periodic):
            return 0.0
        cfg = self.cfg
        if not periodic:
            hit = (
                src.snap.stats.get("accuracy", 95.0)
                - self.stat(tgt, "dodge")
                + (src.snap.level - tgt.snap.level) * cfg.level_diff_hit_pct
            )
            hit = max(cfg.min_hit_pct, min(100.0, hit))
            if not self.rng.chance(hit):
                tgt.dodges += 1
                self.emit("DODGE", actor_id=src.id, target_id=tgt.id, ability_code=source)
                self.fire(tgt, "on_dodge", src)
                return 0.0
        amount = flat if flat is not None else self.stat(src, src.snap.power_stat) * pct / 100.0
        if cfg.damage_variance_pct and not periodic:
            v = cfg.damage_variance_pct / 100.0
            amount *= self.rng.uniform(1 - v, 1 + v)
        crit = False
        if not periodic:
            crit = guaranteed_crit or self.rng.chance(min(self.stat(src, "crit_chance"), cfg.crit_cap_pct))
            if crit:
                amount *= max(100.0, self.stat(src, "crit_damage")) / 100.0
        blocked = False
        if (
            dtype == PHYSICAL
            and not periodic
            and self.stat(tgt, "block") > 0
            and self.rng.chance(min(self.stat(tgt, "block"), 60.0))
        ):
            amount *= 1 - min(90.0, self.stat(tgt, "block_efficiency")) / 100.0
            blocked = True
        if dtype != TRUE_DAMAGE:
            if dtype == PHYSICAL:
                defense = self.stat(tgt, "armor")
                pen = min(cfg.max_penetration_pct, self.stat(src, "armor_penetration") + armor_ignore)
            else:
                defense = self.stat(tgt, "magic_resist") * (1 + self.stat(tgt, "elemental_resist") / 100.0)
                pen = min(cfg.max_penetration_pct, self.stat(src, "magic_penetration") + armor_ignore)
            defense *= 1 - pen / 100.0
            mitigation = defense / (defense + cfg.armor_k * src.snap.level + cfg.armor_k_base)
            amount *= 1 - min(cfg.max_mitigation_pct / 100.0, mitigation)
        bonus = self.damage_bonus(src, tgt, dtype)
        if self.stance and src.side == "players":
            bonus += self.stance.damage_percent
        amount *= max(0.0, 1 + bonus / 100.0)
        amount *= 1 + self.debuff_percent(tgt, "vulnerability") / 100.0
        amount *= 1 - min(90.0, self.debuff_percent(src, "weaken")) / 100.0
        dr = self.damage_reduction(tgt)
        if self.stance and tgt.side == "players":
            dr -= self.stance.damage_taken_percent
        amount *= 1 - max(-100.0, min(dr, self.cfg.max_damage_reduction_pct)) / 100.0
        amount *= self.coeff.get("damage", 1.0)
        amount = max(0.0, amount)
        absorbed = self._absorb(tgt, amount)
        dealt = amount - absorbed
        tgt.hp -= dealt
        src.damage_dealt += amount
        tgt.damage_taken += amount
        tgt.shield_absorbed += absorbed
        if not periodic:
            src.hits += 1
            src.hit_count += 1
            if crit:
                src.crits += 1
            if blocked:
                tgt.blocks += 1
        if tgt.side == "enemies":
            tgt.threat[src.id] = (
                tgt.threat.get(src.id, 0.0) + amount * self.stat(src, "threat") / 100.0 * cfg.threat_damage_factor
            )
        ls = min(self.stat(src, "lifesteal"), cfg.lifesteal_cap_pct)
        if ls > 0 and dealt > 0:
            self._restore(src, src, dealt * ls / 100.0, source="lifesteal", count_heal=True)
        event = "CRIT" if crit else ("BLOCK" if blocked else ("TICK" if periodic else "HIT"))
        self.emit(
            event, actor_id=src.id, target_id=tgt.id, ability_code=source, amount=round(amount, 2), damage_type=dtype
        )
        if not periodic:
            self.fire(src, "on_hit", tgt)
            if crit:
                self.fire(src, "on_crit", tgt)
            if blocked:
                self.fire(tgt, "on_block", src)
            self._every_n(src, tgt)
        self.fire(tgt, "on_damage_taken", src)
        self._thresholds(tgt, src)
        if tgt.hp <= 0 and tgt.alive:
            self._die(tgt, src)
        return amount

    def _absorb(self, tgt: Actor, amount: float) -> float:
        absorbed = 0.0
        for sh in tgt.shields:
            if sh[1] <= self.now or sh[0] <= 0:
                continue
            take = min(sh[0], amount - absorbed)
            sh[0] -= take
            absorbed += take
            if absorbed >= amount:
                break
        tgt.shields = [s for s in tgt.shields if s[0] > 0 and s[1] > self.now]
        return absorbed

    def _die(self, tgt: Actor, killer: Actor) -> None:
        tgt.alive = False
        tgt.hp = 0.0
        killer.kills += 1
        self.emit("DEATH", actor_id=killer.id, target_id=tgt.id)
        self.fire(killer, "on_kill", tgt)
        for k in [k for k, p in self.periodics.items() if p.target_id == tgt.id]:
            del self.periodics[k]

    def heal(
        self,
        src: Actor,
        tgt: Actor,
        pct: float,
        *,
        source: str,
        scope: str = "outgoing",
        periodic_amount: float | None = None,
    ) -> float:
        if not tgt.alive:
            return 0.0
        if periodic_amount is not None:
            amount = periodic_amount
            crit = False
        else:
            amount = self.stat(src, "healing_power") * pct / 100.0
            amount *= 1 + self.heal_bonus(src, tgt, scope) / 100.0
            crit = self.rng.chance(min(self.stat(src, "crit_chance"), self.cfg.crit_cap_pct))
            if crit:
                amount *= 1.5
        if "healing_received" in tgt.snap.stats:
            amount *= max(0.0, self.stat(tgt, "healing_received")) / 100.0
        amount *= self.coeff.get("healing", 1.0)
        effective = self._restore(src, tgt, amount, source=source, count_heal=True)
        self.emit(
            "HEAL" if not crit else "CRIT_HEAL",
            actor_id=src.id,
            target_id=tgt.id,
            ability_code=source,
            amount=round(effective, 2),
        )
        self.fire(src, "on_heal", tgt)
        if crit:
            self.fire(src, "on_crit_heal", tgt)
        if tgt is not src:
            self.fire(tgt, "on_heal", src)
        if tgt.side == "players":
            for foe in self.foes(tgt):
                foe.threat[src.id] = foe.threat.get(src.id, 0.0) + effective * self.cfg.threat_heal_factor
        return effective

    def _restore(self, src: Actor, tgt: Actor, amount: float, *, source: str, count_heal: bool) -> float:
        missing = tgt.max_hp - tgt.hp
        effective = min(missing, max(0.0, amount))
        tgt.hp += effective
        if count_heal:
            src.healing_done += effective
            src.overhealing += max(0.0, amount - effective)
        return effective

    def add_shield(self, src: Actor, tgt: Actor, amount: float, duration: float) -> None:
        amount *= 1 + self.stat(src, "shield_power") / 1000.0
        tgt.shields.append([amount, self.now + duration])
        src.shield_granted += amount
        self.emit("SHIELD", actor_id=src.id, target_id=tgt.id, amount=round(amount, 2))

    def gain_resource(self, a: Actor, code: str, amount: float) -> None:
        if code in a.resources:
            a.resources[code] = min(self.res_cap(a, code), a.resources[code] + amount)
        elif code in a.stack_defs or code in ("opportunity", "combo", "aim"):
            self.gain_stack(a, code, int(amount))

    def gain_stack(
        self,
        a: Actor,
        code: str,
        amount: int,
        max_stacks: int | None = None,
        per_stack: tuple[dict[str, Any], ...] | None = None,
    ) -> None:
        if code not in a.stack_defs:
            a.stack_defs[code] = (max_stacks or 5, per_stack or ())
        cap = self.stack_cap(a, code)
        a.stacks[code] = min(cap, a.stacks.get(code, 0) + amount)
        if code in a.resources:
            a.resources[code] = min(self.res_cap(a, code), float(a.stacks[code]))

    # ------------------------------------------------------------------ effect application
    def targets_for(self, a: Actor, rule: str, context: Actor | None) -> list[Actor]:
        if rule == "self":
            return [a]
        if rule == "party":
            return self.allies(a)
        if rule == "lowest_hp_ally":
            return [self.lowest_ally(a)]
        if rule == "enemy_all":
            return self.foes(a)
        if rule == "target":
            return [context] if context and context.alive else []
        tgt = context if context and context.alive and context.side != a.side else self.pick_target(a)
        return [tgt] if tgt else []

    def apply(self, a: Actor, eff: dict[str, Any], context: Actor | None, key: str, source: str) -> None:
        et, p = eff["effect_type"], eff.get("params", {})
        if et == "DAMAGE":
            tgts = self.targets_for(a, "enemy_single", context)
            for t in tgts:
                self.deal_damage(
                    a,
                    t,
                    p["percent_of_power"],
                    p.get("damage_type", a.snap.base_damage_type),
                    source=source,
                    guaranteed_crit=p.get("guaranteed_crit", False),
                    armor_ignore=p.get("armor_ignore_percent", 0),
                )
        elif et == "HEAL":
            for t in self.targets_for(a, p.get("target", "self"), context):
                self.heal(a, t, p["percent_of_power"], source=source)
        elif et == "SHIELD":
            for t in self.targets_for(a, p.get("target", "self"), context):
                amount = t.max_hp * p.get("percent_max_hp", 0) / 100.0 + p.get("flat", 0)
                self.add_shield(a, t, amount, p.get("duration_s", 6.0))
        elif et == "RESOURCE_GAIN":
            self.gain_resource(a, p["resource"], p["amount"])
        elif et in ("DOT", "HOT"):
            heal = et == "HOT"
            tgts = (
                self.targets_for(a, p.get("target", "self"), context)
                if heal
                else self.targets_for(a, "enemy_single", context)
            )
            for t in tgts:
                self.add_periodic(a, t, p, key, heal)
        elif et == "DEBUFF":
            tgts = self.targets_for(a, "enemy_single", context)
            for t in tgts:
                self.add_debuff(a, t, p, key)
        elif et == "BUFF":
            for t in self.targets_for(a, p.get("target", "self"), context):
                self.add_timed(t, f"{key}", tuple(p["effects"]), p["duration_s"], p.get("max_stacks", 1), a.id, False)
        elif et == "STACK_GAIN":
            self.gain_stack(
                a, p["stack_code"], int(p.get("amount", 1)), int(p.get("max_stacks", 5)), tuple(p.get("per_stack", ()))
            )
        elif et == "EVERY_N_HITS":
            n = a.counters.get(key, 0) + 1
            a.counters[key] = n
            if n % int(p["n"]) == 0:
                for j, nested in enumerate(p["effects"]):
                    self.apply(a, nested, context, f"{key}.{j}", source)
        elif et == "PROC_CHANCE":
            self._try_proc(a, key, p, context)
        elif et == "DAMAGE_REDUCTION" and p.get("duration_s"):
            self.add_timed(
                a,
                key,
                ({"effect_type": "DAMAGE_REDUCTION", "params": {"percent": p["percent"]}},),
                p["duration_s"],
                p.get("max_stacks", 1),
                a.id,
                False,
            )
        elif et == "AURA":
            for t in self.allies(a) if p.get("scope", "party") == "party" else [a]:
                self.add_timed(t, key, tuple(p["effects"]), 10.0, 1, a.id, False)
        elif et not in NON_COMBAT_TYPES:
            # permanent-style modifier granted by an instant context (e.g. inside a proc): short buff
            self.add_timed(a, key, (eff,), 6.0, 1, a.id, False)

    def add_timed(
        self,
        t: Actor,
        key: str,
        effects: tuple[dict[str, Any], ...],
        duration: float,
        max_stacks: int,
        source_id: str,
        is_debuff: bool,
        kind: str | None = None,
        percent: float = 0.0,
    ) -> None:
        src = self.by_id[source_id]
        duration_stat = "debuff_duration" if is_debuff else "buff_duration"
        if duration_stat in src.snap.stats:
            duration *= max(10.0, self.stat(src, duration_stat)) / 100.0
        for existing in t.timed:
            if existing.key == key and existing.source_id == source_id and existing.expires_at > self.now:
                existing.stacks = min(max_stacks, existing.stacks + 1)
                existing.expires_at = self.now + duration
                return
        t.timed.append(Timed(key, effects, self.now + duration, 1, max_stacks, source_id, is_debuff, kind, percent))
        t.timed = [x for x in t.timed if x.expires_at > self.now]
        if not is_debuff:
            self.by_id[source_id].buff_uptime += duration

    def add_debuff(self, src: Actor, tgt: Actor, p: dict[str, Any], key: str) -> None:
        kind = p["kind"]
        dur = (
            p["duration_s"] * self.coeff.get("cc_duration", 1.0)
            if kind in ("root", "freeze", "silence")
            else p["duration_s"]
        )
        effects: tuple[dict[str, Any], ...] = ({"stat": p.get("stat")},) if kind == "stat" else ()
        self.add_timed(tgt, key, effects, dur, p.get("max_stacks", 1), src.id, True, kind, p.get("percent", 0))
        src.debuffs_applied += 1
        if kind == "freeze":
            tgt.frozen_until = max(tgt.frozen_until, self.now + dur)
        self.emit("DEBUFF", actor_id=src.id, target_id=tgt.id, kind=kind)

    def add_periodic(self, src: Actor, tgt: Actor, p: dict[str, Any], key: str, heal: bool) -> None:
        pkey = f"{key}>{tgt.id}"
        power = self.stat(src, "healing_power" if heal else src.snap.power_stat)
        per_tick = power * p["percent_of_power"] / 100.0
        if heal:
            per_tick *= 1 + self.heal_bonus(src, tgt, "hot") / 100.0
        else:
            per_tick *= 1 + self.damage_bonus(src, tgt, p.get("damage_type", PHYSICAL)) / 100.0
        tick = float(p.get("tick_s", 1.0))
        existing = self.periodics.get(pkey)
        if existing and existing.expires_at > self.now:
            existing.stacks = min(existing.max_stacks, existing.stacks + 1)
            existing.expires_at = self.now + p["duration_s"]
            existing.per_tick = per_tick
            return
        self.periodics[pkey] = Periodic(
            pkey,
            src.id,
            tgt.id,
            per_tick,
            tick,
            self.now + p["duration_s"],
            1,
            int(p.get("max_stacks", 1)),
            heal,
            p.get("damage_type", "physical"),
        )
        self.push(self.now + tick, "TICK", pkey)

    # ------------------------------------------------------------------ triggers
    def fire(self, a: Actor, trigger: str, other: Actor | None) -> None:
        if not a.alive or self.proc_depth > 0:
            return
        entries = list(a.procs.get(trigger, ()))
        for t in a.timed:
            if t.expires_at > self.now:
                for j, e in enumerate(t.effects):
                    if e.get("effect_type") == "PROC_CHANCE" and e["params"].get("trigger", "on_hit") == trigger:
                        entries.append((f"{t.key}.p{j}", e["params"]))
        for ally in self.actors:
            if ally.side == a.side and ally.alive:
                for j, e in enumerate(ally.party_auras):
                    if e["effect_type"] == "PROC_CHANCE" and e["params"].get("trigger", "on_hit") == trigger:
                        entries.append((f"{ally.id}:aura{j}", e["params"]))
        for key, p in entries:
            self._try_proc(a, key, p, other)

    def _try_proc(self, a: Actor, key: str, p: dict[str, Any], other: Actor | None) -> None:
        if a.icd_ready.get(key, 0.0) > self.now:
            return
        chance = p["chance_percent"] * (1 + self.stat(a, "proc_consistency") / 1000.0)
        if not self.rng.chance(chance):
            return
        if p.get("internal_cooldown_s"):
            a.icd_ready[key] = self.now + p["internal_cooldown_s"]
        a.procs_fired[key] = a.procs_fired.get(key, 0) + 1
        self.emit("PROC", actor_id=a.id, proc=key)
        self.proc_depth += 1
        try:
            for j, nested in enumerate(p["effects"]):
                self.apply(a, nested, other, f"{key}.{j}", key)
        finally:
            self.proc_depth -= 1

    def _every_n(self, a: Actor, target: Actor) -> None:
        for key, p in a.every_n:
            n = a.counters.get(key, 0) + 1
            a.counters[key] = n
            if n % int(p["n"]) == 0:
                a.procs_fired[key] = a.procs_fired.get(key, 0) + 1
                for j, nested in enumerate(p["effects"]):
                    self.apply(a, nested, target, f"{key}.{j}", key)

    def _thresholds(self, a: Actor, other: Actor | None) -> None:
        """Instant effects inside THRESHOLD_TRIGGER fire on false→true transitions."""
        if not a.alive:
            return
        for key, p in a.thresholds:
            instant = [e for e in p["effects"] if e["effect_type"] in INSTANT_TYPES]
            if not instant:
                continue
            now_true = self.check(a, other, p["condition"])
            was = a.threshold_state.get(key, False)
            a.threshold_state[key] = now_true
            if now_true and not was:
                if p.get("once_per_combat") and key in a.threshold_used:
                    continue
                a.threshold_used.add(key)
                a.procs_fired[key] = a.procs_fired.get(key, 0) + 1
                for j, e in enumerate(instant):
                    self.apply(a, e, other, f"{key}.{j}", key)

    # ------------------------------------------------------------------ actions
    def can_use(self, a: Actor, ab: AbilitySnapshot) -> bool:
        if a.cooldown_ready.get(ab.code, 0.0) > self.now:
            return False
        if ab.cost_resource and ab.cost_amount:
            cost = ab.cost_amount * (
                1
                + (
                    self.cost_mod(a, ab.cost_resource)
                    + (self.stance.resource_cost_percent if self.stance and a.side == "players" else 0)
                )
                / 100.0
            )
            have = a.resources.get(ab.cost_resource, float(a.stacks.get(ab.cost_resource, 0)))
            if have < cost - 1e-9:
                return False
        return True

    def use_ability(self, a: Actor, ab: AbilitySnapshot) -> float:
        if ab.cost_resource and ab.cost_amount:
            cost = ab.cost_amount * (
                1
                + (
                    self.cost_mod(a, ab.cost_resource)
                    + (self.stance.resource_cost_percent if self.stance and a.side == "players" else 0)
                )
                / 100.0
            )
            if ab.cost_resource in a.resources:
                a.resources[ab.cost_resource] -= cost
            else:
                a.stacks[ab.cost_resource] = max(0, a.stacks.get(ab.cost_resource, 0) - round(cost))
            a.resource_spent[ab.cost_resource] = a.resource_spent.get(ab.cost_resource, 0.0) + cost
            self.fire(a, "on_resource_spent", None)
        cdr, no_cd = self.cooldown_mods(a, ab.tags)
        if ab.cooldown_s and not self.rng.chance(no_cd):
            a.cooldown_ready[ab.code] = self.now + ab.cooldown_s * max(0.1, 1 + cdr / 100.0)
        a.abilities_used[ab.code] = a.abilities_used.get(ab.code, 0) + 1
        self.emit("ABILITY", actor_id=a.id, ability_code=ab.code)
        target = self.pick_target(a) if ab.target_rule in ("enemy_single", "enemy_all") else None
        if ab.target_rule == "enemy_all":
            for foe in self.foes(a):
                for j, e in enumerate(ab.effects):
                    if e["effect_type"] in ("DAMAGE", "DOT", "DEBUFF"):
                        self.apply(a, e, foe, f"{a.id}:{ab.code}.{j}", ab.code)
            for j, e in enumerate(ab.effects):
                if e["effect_type"] not in ("DAMAGE", "DOT", "DEBUFF"):
                    self.apply(a, e, None, f"{a.id}:{ab.code}.{j}", ab.code)
        else:
            for j, e in enumerate(ab.effects):
                self.apply(a, e, target, f"{a.id}:{ab.code}.{j}", ab.code)
        self.fire(a, "on_ability_cast", target)
        return max(self.cfg.gcd_s, ab.cast_time_s)

    def attack_interval(self, a: Actor) -> float:
        speed = self.stat(a, "attack_speed") or 100.0
        if self.stance and a.side == "players":
            speed *= 1 + self.stance.attack_speed_percent / 100.0
        return max(self.cfg.min_attack_interval_s, a.snap.base_attack_interval_s * 100.0 / max(1.0, speed))

    def act(self, a: Actor) -> None:
        if not a.alive:
            return
        if a.frozen_until > self.now:
            self.push(a.frozen_until, "ACT", a.id)
            return
        self._thresholds(a, self.pick_target(a))
        if a.side == "players":
            self._maybe_potion(a)
        selector = self.selector if a.side == "players" else self.enemy_selector
        ability = selector(self, a)
        if ability is not None and self.can_use(a, ability):
            delay = self.use_ability(a, ability)
        else:
            target = self.pick_target(a)
            if target is None:
                return
            self.deal_damage(a, target, 100.0, a.snap.base_damage_type, source="basic_attack")
            delay = self.attack_interval(a)
        self.push(self.now + delay, "ACT", a.id)

    def _maybe_potion(self, a: Actor) -> None:
        s = self.data.strategy
        if a.potions_left > 0 and self.now >= a.potion_ready_at and self.hp_pct(a) < s.potion_threshold_pct:
            a.potions_left -= 1
            a.potions_used += 1
            a.potion_ready_at = self.now + s.potion_cooldown_s
            healed = self._restore(a, a, a.max_hp * s.potion_heal_pct / 100.0, source="potion", count_heal=False)
            self.emit("POTION", actor_id=a.id, amount=round(healed, 2))

    def regen(self) -> None:
        tick = self.cfg.regen_tick_s
        for a in self.actors:
            if not a.alive:
                continue
            for r in a.snap.resources:
                if r.code in a.resources:
                    regen = r.regen_per_s * (1 + self.stat(a, "resource_regen") / 100.0 if r.regen_per_s else 1)
                    a.resources[r.code] = max(
                        0.0, min(self.res_cap(a, r.code), a.resources[r.code] + (regen - r.decay_per_s) * tick)
                    )
            hp_regen = self.stat(a, "hp_regen")
            if hp_regen > 0 and a.hp < a.max_hp:
                self._restore(a, a, hp_regen * tick, source="regen", count_heal=False)

    def tick_periodic(self, key: str) -> None:
        p = self.periodics.get(key)
        if p is None:
            return
        src, tgt = self.by_id[p.source_id], self.by_id[p.target_id]
        if not tgt.alive:
            del self.periodics[key]
            return
        amount = p.per_tick * p.stacks
        if p.heal:
            self.heal(src, tgt, 0, source=key, periodic_amount=amount)
        else:
            self.deal_damage(src, tgt, 0, p.damage_type, source=key, periodic=True, flat=amount)
        if self.now + p.tick_s <= p.expires_at + 1e-9 and key in self.periodics:
            self.push(self.now + p.tick_s, "TICK", key)
        else:
            self.periodics.pop(key, None)

    # ------------------------------------------------------------------ main loop
    def outcome(self) -> str | None:
        if not any(a.alive for a in self.actors if a.side == "enemies"):
            return "win"
        if not any(a.alive for a in self.actors if a.side == "players"):
            return "loss"
        return None

    def run(self) -> CombatResult:
        for a in self.actors:
            self.fire(a, "combat_start", None)
            self.push(0.05 * a.index + (0.0 if a.side == "players" else 0.5), "ACT", a.id)
        self.push(self.cfg.regen_tick_s, "REGEN", "")
        result = None
        while self.queue:
            t, _, kind, ref = heapq.heappop(self.queue)
            if t > self.cfg.max_duration_s:
                self.now = self.cfg.max_duration_s
                result = "timeout"
                break
            self.now = t
            self.events += 1
            if kind == "ACT":
                self.act(self.by_id[ref])
            elif kind == "TICK":
                self.tick_periodic(ref)
            elif kind == "REGEN":
                self.regen()
                self.push(self.now + self.cfg.regen_tick_s, "REGEN", "")
            result = self.outcome()
            if result:
                break
        if result is None:
            result = "timeout"
        self.emit("END", outcome=result)
        return self._result(result)

    def _result(self, outcome: str) -> CombatResult:
        combatants = tuple(
            CombatantResult(
                id=a.id,
                alive=a.alive,
                hp_end=round(max(0.0, a.hp), 3),
                damage_dealt=round(a.damage_dealt, 3),
                damage_taken=round(a.damage_taken, 3),
                healing_done=round(a.healing_done, 3),
                overhealing=round(a.overhealing, 3),
                shield_absorbed=round(a.shield_absorbed, 3),
                shield_granted=round(a.shield_granted, 3),
                resource_spent={k: round(v, 3) for k, v in sorted(a.resource_spent.items())},
                hits=a.hits,
                crits=a.crits,
                dodges=a.dodges,
                blocks=a.blocks,
                kills=a.kills,
                abilities_used=dict(sorted(a.abilities_used.items())),
                procs=dict(sorted(a.procs_fired.items())),
                potions_used=a.potions_used,
                buff_uptime_s=round(a.buff_uptime, 3),
                debuffs_applied=a.debuffs_applied,
            )
            for a in self.actors
        )
        killed = tuple(a.id for a in self.actors if a.side == "enemies" and not a.alive)
        return CombatResult(
            outcome=outcome,
            elapsed_s=round(self.now, 3),
            seed=self.data.seed,
            rng_draws=self.rng.draws,
            events_processed=self.events,
            combatants=combatants,
            killed_enemy_ids=killed,
            log=tuple(self.log),
            log_truncated=self.log_truncated,
            content_version=self.data.content_version,
        )


def simulate(
    data: CombatInput,
    cfg: CombatConfig | None = None,
    *,
    selector: ActionSelector | None = None,
    enemy_selector: ActionSelector | None = None,
) -> CombatResult:
    return Battle(data, cfg or CombatConfig(), selector, enemy_selector).run()
