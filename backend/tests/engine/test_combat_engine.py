import hashlib
import json
import time

import pytest

from app.game_engine.combat.engine import Battle, simulate
from app.game_engine.combat.models import AbilitySnapshot, CombatConfig, CombatInput, CombatStrategy, ResourceSnapshot
from tests.engine.factories import eff, enemy, player

CFG = CombatConfig()


def digest(result) -> str:  # type: ignore[no-untyped-def]
    return hashlib.sha256(json.dumps(result.model_dump(mode="json"), sort_keys=True).encode()).hexdigest()


def canonical_input(seed: int = 2026) -> CombatInput:
    p = player(
        effects=(
            eff(
                "PROC_CHANCE",
                chance_percent=30,
                trigger="on_hit",
                effects=[eff("DOT", damage_type="poison", percent_of_power=5, duration_s=6, max_stacks=5)],
            ),
            eff("EVERY_N_HITS", n=4, effects=[eff("DAMAGE", percent_of_power=80)]),
            eff(
                "THRESHOLD_TRIGGER",
                condition={"metric": "self_hp_pct", "op": "lt", "value": 50},
                once_per_combat=True,
                effects=[eff("SHIELD", percent_max_hp=15, duration_s=10)],
            ),
            eff("DAMAGE_MULTIPLIER", percent=15, condition={"metric": "target_hp_pct", "op": "lt", "value": 35}),
        )
    )
    return CombatInput(players=(p,), enemies=(enemy("e0"), enemy("e1"), enemy("e2")), seed=seed, content_version=7)


def test_same_snapshot_and_seed_gives_identical_result() -> None:
    a, b = simulate(canonical_input(), CFG), simulate(canonical_input(), CFG)
    assert a == b and digest(a) == digest(b)
    assert simulate(canonical_input(2027), CFG) != a
    assert a.content_version == 7 and a.seed == 2026


# Phase 21: digests re-baselined only for the new result fields (damage_prevented, ally_buff_uptime_s);
# combat math verified unchanged against the previous digests.
GOLDEN_DIGESTS = {
    1: "247c47d9646c9aed9b72908ed3a3a36dcb333e8cddfc85c40b6e9a5700286ba5",
    42: "ea696e5faf8e2884428f6b445978156dc7971ea36586526b91d7293e88867b78",
    2026: "5fc60f1d075814ca62b413b257f487f931bbfb1af7634aa1d5bdfe821b640996",
}


@pytest.mark.parametrize("seed", [1, 42, 2026])
def test_golden_results(seed: int) -> None:
    """Golden digests lock combat math; update deliberately (and bump balance version) when rules change."""
    result = simulate(canonical_input(seed), CFG)
    expected = GOLDEN_DIGESTS[seed]
    assert digest(result) == expected, f"combat output changed for seed {seed}"


def test_result_shape_and_log_is_structured() -> None:
    r = simulate(canonical_input(), CFG)
    assert r.outcome in ("win", "loss", "timeout")
    types = {e["event_type"] for e in r.log}
    assert {"HIT", "END"} <= types
    assert all(isinstance(e["t"], float) and "event_type" in e for e in r.log)
    me = r.combatants[0]
    assert me.damage_dealt > 0 and me.hits > 0 and any(k.endswith(":e1") for k in me.procs)


def test_next_event_stepping_not_tick_loop() -> None:
    r = simulate(canonical_input(), CFG)
    # A 180 s cap at 1 ms resolution would be 180k steps; we process only a few hundred events.
    assert r.events_processed < 2000


def test_death_loss_and_timeout() -> None:
    weak = player(stats={"max_hp": 50, "attack_power": 1})
    boss = enemy(stats={"max_hp": 100000, "attack_power": 500}, boss=True)
    assert simulate(CombatInput(players=(weak,), enemies=(boss,), seed=1), CFG).outcome == "loss"
    tanky = enemy(stats={"max_hp": 10**9, "attack_power": 0})
    r = simulate(CombatInput(players=(player(),), enemies=(tanky,), seed=1), CombatConfig(max_duration_s=20))
    assert r.outcome == "timeout" and r.elapsed_s == 20


def test_dodge_floor_and_accuracy() -> None:
    slippery = enemy(stats={"dodge": 200})
    r = simulate(
        CombatInput(players=(player(stats={"attack_power": 1}),), enemies=(slippery,), seed=3),
        CombatConfig(max_duration_s=60),
    )
    me = r.combatants[0]
    them = r.combatants[1]
    assert me.hits > 0 and them.dodges > 0  # min hit chance keeps combat progressing


def test_shield_absorbs_before_hp() -> None:
    p = player(
        effects=(
            eff(
                "PROC_CHANCE",
                chance_percent=100,
                trigger="combat_start",
                effects=[eff("SHIELD", flat=100000, duration_s=999)],
            ),
        )
    )
    r = simulate(CombatInput(players=(p,), enemies=(enemy(),), seed=5), CFG)
    me = r.combatants[0]
    assert me.shield_absorbed > 0 and me.hp_end == 2000


def test_dot_and_hot_tick() -> None:
    p = player(
        stats={"attack_power": 50},
        effects=(
            eff(
                "PROC_CHANCE",
                chance_percent=100,
                trigger="on_hit",
                effects=[eff("DOT", damage_type="poison", percent_of_power=10, duration_s=6, max_stacks=3)],
            ),
            eff(
                "PROC_CHANCE",
                chance_percent=100,
                trigger="on_damage_taken",
                internal_cooldown_s=5,
                effects=[eff("HOT", percent_of_power=20, duration_s=6, target="self")],
            ),
        ),
    )
    r = simulate(CombatInput(players=(p,), enemies=(enemy(),), seed=11), CFG)
    ticks = [e for e in r.log if e["event_type"] == "TICK"]
    assert ticks and r.combatants[0].healing_done > 0


def test_freeze_delays_enemy_actions() -> None:
    frost = player(
        effects=(
            eff(
                "PROC_CHANCE",
                chance_percent=100,
                trigger="on_hit",
                effects=[eff("DEBUFF", kind="freeze", duration_s=5)],
            ),
        )
    )
    free = player()
    e = enemy(stats={"max_hp": 5000})
    r_frost = simulate(CombatInput(players=(frost,), enemies=(e,), seed=9), CombatConfig(max_duration_s=30))
    r_free = simulate(CombatInput(players=(free,), enemies=(e,), seed=9), CombatConfig(max_duration_s=30))
    assert r_frost.combatants[0].damage_taken < r_free.combatants[0].damage_taken


def test_threat_makes_enemies_target_the_tank() -> None:
    tank = player("tank", stats={"threat": 500, "max_hp": 5000, "armor": 2000, "attack_power": 40}, role="tank")
    dps = player("dps", stats={"threat": 50, "attack_power": 200})
    r = simulate(CombatInput(players=(dps, tank), enemies=(enemy(stats={"max_hp": 6000}),), seed=4), CFG)
    by = {c.id: c for c in r.combatants}
    assert by["tank"].damage_taken > by["dps"].damage_taken * 2


def test_lifesteal_and_damage_reduction_cap() -> None:
    vamp = player(stats={"lifesteal": 25, "max_hp": 800})
    r = simulate(CombatInput(players=(vamp,), enemies=(enemy(stats={"attack_power": 120}),), seed=2), CFG)
    assert r.combatants[0].healing_done > 0
    b = Battle(
        CombatInput(players=(player(effects=(eff("DAMAGE_REDUCTION", percent=90),)),), enemies=(enemy(),), seed=1), CFG
    )
    assert b.damage_reduction(b.actors[0]) == CFG.max_damage_reduction_pct


def test_guaranteed_crit_and_every_n() -> None:
    p = player(effects=(eff("EVERY_N_HITS", n=2, effects=[eff("DAMAGE", percent_of_power=50, guaranteed_crit=True)]),))
    r = simulate(CombatInput(players=(p,), enemies=(enemy(stats={"max_hp": 4000}),), seed=6), CFG)
    assert r.combatants[0].crits > 0 and any(k.endswith(":e0") for k in r.combatants[0].procs)


def test_threshold_once_per_combat() -> None:
    p = player(
        stats={"max_hp": 3000},
        effects=(
            eff(
                "THRESHOLD_TRIGGER",
                condition={"metric": "self_hp_pct", "op": "lt", "value": 90},
                once_per_combat=True,
                effects=[eff("HEAL", percent_of_power=1000)],
            ),
        ),
    )
    r = simulate(CombatInput(players=(p,), enemies=(enemy(stats={"attack_power": 150, "max_hp": 5000}),), seed=8), CFG)
    assert list(r.combatants[0].procs.values()) == [1]


def test_stacks_and_buff_modifiers_raise_output() -> None:
    stacking = player(
        effects=(
            eff(
                "PROC_CHANCE",
                chance_percent=100,
                trigger="on_hit",
                effects=[
                    eff(
                        "STACK_GAIN", stack_code="tempo", max_stacks=10, per_stack=[eff("DAMAGE_MULTIPLIER", percent=5)]
                    )
                ],
            ),
        )
    )
    tough = enemy(stats={"max_hp": 20000, "attack_power": 1})
    a = simulate(CombatInput(players=(stacking,), enemies=(tough,), seed=3), CombatConfig(max_duration_s=60))
    b = simulate(CombatInput(players=(player(),), enemies=(tough,), seed=3), CombatConfig(max_duration_s=60))
    assert a.combatants[0].damage_dealt > b.combatants[0].damage_dealt * 1.2


def test_armor_mitigation_and_pvp_coefficient() -> None:
    soft = enemy(stats={"armor": 0, "max_hp": 10**7, "attack_power": 1})
    hard = enemy(stats={"armor": 5000, "max_hp": 10**7, "attack_power": 1})
    cfg = CombatConfig(max_duration_s=30)
    dmg_soft = simulate(CombatInput(players=(player(),), enemies=(soft,), seed=1), cfg).combatants[0].damage_dealt
    dmg_hard = simulate(CombatInput(players=(player(),), enemies=(hard,), seed=1), cfg).combatants[0].damage_dealt
    assert dmg_hard < dmg_soft
    pvp = simulate(CombatInput(players=(player(),), enemies=(soft,), seed=1, context="pvp"), cfg)
    assert pvp.combatants[0].damage_dealt < dmg_soft


def test_ability_execution_costs_cooldowns_and_triggers() -> None:
    slam = AbilitySnapshot(
        code="slam",
        ability_type="ACTIVE",
        target_rule="enemy_single",
        cost_resource="rage",
        cost_amount=10,
        cooldown_s=6,
        effects=({"effect_type": "DAMAGE", "params": {"percent_of_power": 200}},),
    )
    p = player(
        abilities=(slam,),
        resources=(ResourceSnapshot(code="rage", max=100, start=50, regen_per_s=0, decay_per_s=0),),
        primary="rage",
        effects=(
            eff(
                "PROC_CHANCE",
                chance_percent=100,
                trigger="on_resource_spent",
                effects=[eff("RESOURCE_GAIN", resource="rage", amount=1)],
            ),
        ),
    )

    def selector(battle, actor):  # type: ignore[no-untyped-def]
        return actor.snap.abilities[0] if actor.snap.abilities else None

    r = simulate(
        CombatInput(
            players=(p,),
            enemies=(enemy(stats={"max_hp": 20000}),),
            seed=1,
            strategy=CombatStrategy(mode="ACTIVE_TACTICS"),
        ),
        CombatConfig(max_duration_s=30),
        selector=selector,
    )
    me = r.combatants[0]
    assert 1 <= me.abilities_used["slam"] <= 6 and me.resource_spent["rage"] > 0


def test_benchmark_hundreds_of_encounters_quickly() -> None:
    start = time.perf_counter()
    for seed in range(300):
        simulate(canonical_input(seed), CFG)
    elapsed = time.perf_counter() - start
    assert elapsed < 6.0, f"300 encounters took {elapsed:.2f}s"
