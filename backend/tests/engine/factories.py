from typing import Any

from app.game_engine.combat.models import AbilitySnapshot, CombatantSnapshot, ResourceSnapshot

BASE_PLAYER = {
    "max_hp": 2000,
    "attack_power": 150,
    "spell_power": 60,
    "healing_power": 80,
    "armor": 300,
    "magic_resist": 100,
    "accuracy": 95,
    "dodge": 5,
    "block": 0,
    "block_efficiency": 30,
    "crit_chance": 10,
    "crit_damage": 160,
    "attack_speed": 100,
    "threat": 100,
    "hp_regen": 0,
    "lifesteal": 0,
}
BASE_ENEMY = {
    "max_hp": 900,
    "attack_power": 60,
    "armor": 150,
    "magic_resist": 50,
    "accuracy": 92,
    "dodge": 5,
    "crit_chance": 5,
    "crit_damage": 150,
    "attack_speed": 100,
}


def player(
    pid: str = "p0",
    *,
    stats: dict[str, float] | None = None,
    effects: tuple[dict[str, Any], ...] = (),
    abilities: tuple[AbilitySnapshot, ...] = (),
    level: int = 50,
    role: str = "dps",
    resources: tuple[ResourceSnapshot, ...] = (),
    primary: str | None = None,
) -> CombatantSnapshot:
    return CombatantSnapshot(
        id=pid,
        code="test",
        side="players",
        level=level,
        stats={**BASE_PLAYER, **(stats or {})},
        effects=effects,
        abilities=abilities,
        role=role,  # type: ignore[arg-type]
        resources=resources,
        primary_resource=primary,
    )


def enemy(
    eid: str = "e0",
    *,
    stats: dict[str, float] | None = None,
    level: int = 50,
    boss: bool = False,
    effects: tuple[dict[str, Any], ...] = (),
) -> CombatantSnapshot:
    return CombatantSnapshot(
        id=eid,
        code="wolf",
        side="enemies",
        level=level,
        stats={**BASE_ENEMY, **(stats or {})},
        is_boss=boss,
        effects=effects,
    )


def eff(effect_type: str, **params: Any) -> dict[str, Any]:
    return {"effect_type": effect_type, "params": params}
