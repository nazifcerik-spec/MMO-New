"""Phase 10: passive-only rule resolution (ordering, thresholds, procs, consumables)."""

import pytest

from app.game_engine.combat.engine import simulate
from app.game_engine.combat.models import AbilitySnapshot, CombatConfig, CombatInput, CombatStrategy
from app.game_engine.combat.rules import RuleValidationError, rule_selector, validate_rules
from tests.engine.factories import eff, enemy, player

CFG = CombatConfig(max_duration_s=60)


def _ab(code: str, cooldown: float = 0, tags: tuple[str, ...] = (), **effect: object) -> AbilitySnapshot:
    return AbilitySnapshot(
        code=code,
        ability_type="ACTIVE",
        cooldown_s=cooldown,
        tags=tags,
        effects=(effect or {"effect_type": "DAMAGE", "params": {"percent_of_power": 120}},),  # type: ignore[arg-type]
    )


def _run(rules: list[dict[str, object]], p=None, e=None, seed: int = 7, strategy=None):  # type: ignore[no-untyped-def]
    usage: dict[str, dict[str, int]] = {}
    r = simulate(
        CombatInput(
            players=(p or player(abilities=(_ab("big", cooldown=5), _ab("small"))),),
            enemies=(e or enemy(stats={"max_hp": 30000}),),
            seed=seed,
            strategy=strategy or CombatStrategy(mode="PASSIVE_ONLY"),
        ),
        CFG,
        selector=rule_selector(validate_rules(rules), usage),
    )
    return r, usage.get("p0", {})


def test_rule_order_is_priority_order() -> None:
    first, _ = _run([{"use": {"ability": "big"}}, {"use": {"ability": "small"}}])
    used = first.combatants[0].abilities_used
    assert used.get("big", 0) >= 5 and used.get("small", 0) > 0  # big on cooldown -> falls through to small
    swapped, _ = _run([{"use": {"ability": "small"}}, {"use": {"ability": "big"}}])
    assert "big" not in swapped.combatants[0].abilities_used  # higher-priority rule always wins


def test_threshold_rule_fires_only_below_threshold() -> None:
    heal = _ab("mend", cooldown=2, tags=("heal",), effect_type="HEAL", params={"percent_of_power": 300})
    p = player(abilities=(heal, _ab("small")))
    hard = enemy(stats={"max_hp": 30000, "attack_power": 260})
    rules = [
        {"use": {"tag": "heal"}, "when": [{"kind": "HP_PERCENT", "op": "lt", "value": 60}]},
        {"use": {"ability": "small"}},
    ]
    r, usage = _run(rules, p=p, e=hard)
    assert r.combatants[0].abilities_used.get("mend", 0) > 0 and usage["0"] > 0
    never = [{**rules[0], "when": [{"kind": "HP_PERCENT", "op": "lt", "value": 0}]}, rules[1]]
    r2, _ = _run(never, p=p, e=hard)
    assert "mend" not in r2.combatants[0].abilities_used
    assert r.combatants[0].damage_taken > 0


def test_every_n_actions_cycle() -> None:
    rules = [{"use": {"ability": "small"}, "when": [{"kind": "EVERY_N_ACTIONS", "value": 3}]}]
    _, usage = _run(rules, p=player(abilities=(_ab("small"),)))
    uses, fallback = usage["0"], usage["fallback"]
    assert uses > 0 and fallback >= uses * 2 - 2  # 1 of every 3 actions is the finisher


def test_procs_are_deterministic_per_seed() -> None:
    proc = eff("PROC_CHANCE", chance_percent=30, trigger="on_hit", effects=[eff("DAMAGE", percent_of_power=50)])
    p = player(effects=(proc,))
    a, _ = _run([], p=p, seed=11)
    b, _ = _run([], p=p, seed=11)
    c, _ = _run([], p=p, seed=12)
    assert a == b
    assert a.combatants[0].procs
    assert a.combatants[0].procs != c.combatants[0].procs or a.rng_draws != c.rng_draws
    procs = basic = 0
    for seed in range(1, 21):
        me = _run([], p=p, seed=seed)[0].combatants[0]
        n = sum(me.procs.values())
        procs, basic = procs + n, basic + me.hits - n  # proc damage also counts as a hit
    assert 0.24 < procs / basic < 0.36


@pytest.mark.parametrize("potions", [0, 1, 3])
def test_consumable_limit_and_cooldown(potions: int) -> None:
    strategy = CombatStrategy(mode="PASSIVE_ONLY", potions=potions, potion_threshold_pct=60, potion_cooldown_s=15)
    r, _ = _run([], e=enemy(stats={"max_hp": 60000, "attack_power": 300}), strategy=strategy)
    used = r.combatants[0].potions_used
    assert used <= potions and used <= int(r.elapsed_s // 15) + 1
    if potions:
        assert used >= 1


def test_rule_validation_rejects_bad_input() -> None:
    with pytest.raises(RuleValidationError):
        validate_rules([{"use": {"ability": "x"}}] * 7)
    with pytest.raises(RuleValidationError):
        validate_rules([{"use": {"ability": "x", "tag": "heal"}}])
    with pytest.raises(RuleValidationError):
        validate_rules([{"use": {"ability": "x"}, "when": [{"kind": "EVERY_N_ACTIONS", "value": 1}]}])
    with pytest.raises(RuleValidationError):
        validate_rules([{"use": {"ability": "DROP TABLE"}}])
    with pytest.raises(RuleValidationError):
        validate_rules([{"use": {"ability": "x"}, "when": [{"kind": "PYTHON_EVAL"}]}])


def test_guaranteed_on_hit_proc_does_not_chain() -> None:
    proc = eff("PROC_CHANCE", chance_percent=100, trigger="on_hit", effects=[eff("DAMAGE", percent_of_power=10)])
    me = _run([], p=player(effects=(proc,)))[0].combatants[0]
    procs = sum(me.procs.values())  # one proc per basic hit; proc damage may miss but never re-procs
    assert procs < me.hits <= 2 * procs
