"""Safe priority-rule DSL shared by passive profiles (designer-authored) and Active Tactics (player-authored).

A rule is `{"use": {"ability": code} | {"tag": tag}, "when": [condition, ...]}`; conditions come from a closed
registry with enumerated comparators — nothing is evaluated as code. The first rule whose ability is ready,
affordable and whose conditions all hold is used; otherwise the actor makes a basic attack."""

from collections.abc import Callable
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.game_engine.combat.engine import Actor, Battle
from app.game_engine.combat.models import AbilitySnapshot

Op = Literal["lt", "lte", "gt", "gte", "eq"]
OPS = ("lt", "lte", "gt", "gte", "eq")
CONDITION_KINDS = (
    "HP_PERCENT",
    "RESOURCE_PERCENT",
    "TARGET_TYPE",
    "ENEMY_COUNT",
    "TARGET_HP",
    "BUFF_PRESENT",
    "DEBUFF_PRESENT",
    "COOLDOWN_READY",
    "ALLY_HP_BELOW",
    "STACK_COUNT",
    "COMBAT_TIME",
    "EVERY_N_ACTIONS",
)
MAX_RULES = 6
MAX_CONDITIONS = 4


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RuleCondition(_M):
    kind: Literal[
        "HP_PERCENT",
        "RESOURCE_PERCENT",
        "TARGET_TYPE",
        "ENEMY_COUNT",
        "TARGET_HP",
        "BUFF_PRESENT",
        "DEBUFF_PRESENT",
        "COOLDOWN_READY",
        "ALLY_HP_BELOW",
        "STACK_COUNT",
        "COMBAT_TIME",
        "EVERY_N_ACTIONS",
    ]
    op: Op = "gte"
    value: float = Field(default=0, ge=0, le=100_000)
    target_type: Literal["boss", "elite", "normal"] | None = None
    code: str | None = Field(default=None, max_length=96, pattern=r"^[a-z0-9_]+$")

    @model_validator(mode="after")
    def _shape(self) -> "RuleCondition":
        if self.kind == "TARGET_TYPE" and self.target_type is None:
            raise ValueError("TARGET_TYPE needs target_type")
        if self.kind in ("STACK_COUNT",) and not self.code:
            raise ValueError(f"{self.kind} needs code")
        if self.kind == "EVERY_N_ACTIONS" and self.value < 2:
            raise ValueError("EVERY_N_ACTIONS needs value >= 2")
        return self


class RuleUse(_M):
    ability: str | None = Field(default=None, max_length=96, pattern=r"^[a-z0-9_]+$")
    tag: str | None = Field(default=None, max_length=32, pattern=r"^[a-z_]+$")

    @model_validator(mode="after")
    def _one(self) -> "RuleUse":
        if (self.ability is None) == (self.tag is None):
            raise ValueError("use exactly one of ability or tag")
        return self


class Rule(_M):
    use: RuleUse
    when: tuple[RuleCondition, ...] = Field(default=(), max_length=MAX_CONDITIONS)
    label: str | None = Field(default=None, max_length=64)


class RuleSet(_M):
    rules: tuple[Rule, ...] = Field(default=(), max_length=MAX_RULES)


class RuleValidationError(ValueError):
    pass


def validate_rules(raw: Any, *, max_rules: int = MAX_RULES) -> RuleSet:
    try:
        rs = RuleSet.model_validate({"rules": raw})
    except ValidationError as exc:
        err = exc.errors()[0]
        raise RuleValidationError(f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}") from exc
    if len(rs.rules) > max_rules:
        raise RuleValidationError(f"at most {max_rules} rules")
    return rs


def _cmp(op: str, a: float, b: float) -> bool:
    return {"lt": a < b, "lte": a <= b, "gt": a > b, "gte": a >= b, "eq": a == b}[op]


def rule_selector(
    rules: RuleSet, stats: dict[str, dict[str, int]] | None = None
) -> Callable[[Battle, Actor], AbilitySnapshot | None]:
    """Build an ActionSelector. `stats` (optional) collects per-actor rule usage counts for previews."""
    action_counter: dict[str, int] = {}

    def resolve(battle: Battle, actor: Actor, use: RuleUse) -> AbilitySnapshot | None:
        for ab in actor.snap.abilities:
            if (use.ability and ab.code == use.ability) or (use.tag and use.tag in ab.tags):
                if battle.can_use(actor, ab):
                    return ab
        return None

    def holds(battle: Battle, actor: Actor, ab: AbilitySnapshot, c: RuleCondition) -> bool:
        target = battle.pick_target(actor)
        if c.kind == "HP_PERCENT":
            return _cmp(c.op, battle.hp_pct(actor), c.value)
        if c.kind == "RESOURCE_PERCENT":
            return _cmp(c.op, battle.resource_pct(actor), c.value)
        if c.kind == "TARGET_HP":
            return target is not None and _cmp(c.op, battle.hp_pct(target), c.value)
        if c.kind == "ENEMY_COUNT":
            return _cmp(c.op, float(len(battle.foes(actor))), c.value)
        if c.kind == "TARGET_TYPE":
            if target is None:
                return False
            kind = "boss" if target.snap.is_boss else "elite" if target.snap.is_elite else "normal"
            return kind == c.target_type
        if c.kind == "BUFF_PRESENT" and c.code == "shield":
            present = any(sh[0] > 0 and sh[1] > battle.now for sh in actor.shields)
            return present == (c.value >= 1 or c.op != "eq")
        if c.kind == "BUFF_PRESENT":
            present = any(
                not t.is_debuff and t.expires_at > battle.now and (c.code is None or c.code in t.key)
                for t in actor.timed
            )
            return present == (c.value >= 1 or c.op != "eq")
        if c.kind == "DEBUFF_PRESENT" and c.code == "dot":
            present = target is not None and any(
                not p.heal and p.target_id == target.id and p.source_id == actor.id and p.expires_at > battle.now
                for p in battle.periodics.values()
            )
            return present == (c.value >= 1 or c.op != "eq")
        if c.kind == "DEBUFF_PRESENT":
            present = target is not None and any(
                t.is_debuff and t.expires_at > battle.now and (c.code is None or t.kind == c.code) for t in target.timed
            )
            return present == (c.value >= 1 or c.op != "eq")
        if c.kind == "COOLDOWN_READY":
            return battle.can_use(actor, ab)
        if c.kind == "ALLY_HP_BELOW":
            return battle.hp_pct(battle.lowest_ally(actor)) < c.value
        if c.kind == "STACK_COUNT":
            return _cmp(c.op, float(actor.stacks.get(c.code or "", 0)), c.value)
        if c.kind == "COMBAT_TIME":
            return _cmp(c.op, battle.now, c.value)
        if c.kind == "EVERY_N_ACTIONS":
            return action_counter.get(actor.id, 0) % int(c.value) == 0
        return False

    def selector(battle: Battle, actor: Actor) -> AbilitySnapshot | None:
        action_counter[actor.id] = action_counter.get(actor.id, 0) + 1
        for i, rule in enumerate(rules.rules):
            ab = resolve(battle, actor, rule.use)
            if ab is None:
                continue
            if all(holds(battle, actor, ab, c) for c in rule.when):
                if stats is not None:
                    per = stats.setdefault(actor.id, {})
                    per[str(i)] = per.get(str(i), 0) + 1
                return ab
        if stats is not None:
            per = stats.setdefault(actor.id, {})
            per["fallback"] = per.get("fallback", 0) + 1
        return None

    return selector
