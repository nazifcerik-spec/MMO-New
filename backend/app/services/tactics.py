"""Active Tactics: validation of player priority rules against the character's kit + canonical template.

Rules use the safe DSL in `game_engine.combat.rules` (whitelisted condition kinds, no expressions)."""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ValidationFailedError
from app.game_engine.combat.rules import RuleSet, RuleValidationError, validate_rules
from app.models.abilities import AbilityDefinition
from app.models.character import Character
from app.services import afk_profiles, combat_snapshot
from app.services.content.types.abilities import AbilityLimits
from app.services.content.types.afk_profiles import CombatModes
from app.services.content.types.balance import get_published_balance


async def modes_config(db: AsyncSession) -> CombatModes:
    return await get_published_balance(db, "combat_modes", CombatModes)


def _fail(code: str, message: str, index: int | None = None) -> ValidationFailedError:
    return ValidationFailedError(message, code=code, details={"rule": index} if index is not None else None)


async def validate_tactics(db: AsyncSession, character: Character, raw: list[dict[str, Any]]) -> RuleSet:
    cfg = await modes_config(db)
    try:
        rules = validate_rules(raw, max_rules=cfg.max_rules)
    except RuleValidationError as exc:
        raise _fail("invalid_tactics", str(exc)) from exc
    kit = await combat_snapshot.usable_abilities(db, character)
    by_code = {a.code: a for a in kit}
    tags = {t for a in kit for t in a.tags}
    used: dict[str, AbilityDefinition] = {}
    for i, rule in enumerate(rules.rules):
        if rule.use.ability:
            ability = by_code.get(rule.use.ability)
            if ability is None:
                raise _fail("tactic_ability_unavailable", f"ability {rule.use.ability} is not usable", i)
            used[ability.code] = ability
        elif rule.use.tag not in tags:
            raise _fail("tactic_tag_unavailable", f"no usable ability has tag {rule.use.tag}", i)
        for cond in rule.when:
            if cond.kind == "COOLDOWN_READY" and cond.code and cond.code not in by_code:
                raise _fail("tactic_ability_unavailable", f"ability {cond.code} is not usable", i)
    limits = await get_published_balance(db, "ability_limits", AbilityLimits)
    actives = sum(1 for a in used.values() if a.ability_type == "ACTIVE")
    ultimates = sum(1 for a in used.values() if a.ability_type == "ULTIMATE")
    if actives > limits.max_core_actives or ultimates > limits.max_ultimates:
        raise _fail(
            "tactics_loadout_limit",
            f"tactics may reference at most {limits.max_core_actives} core actives and {limits.max_ultimates} ultimate",
        )
    return rules


async def _validator(db: AsyncSession, character: Character, raw: list[dict[str, Any]]) -> None:
    await validate_tactics(db, character, raw)


afk_profiles.TACTICS_VALIDATORS.append(_validator)
