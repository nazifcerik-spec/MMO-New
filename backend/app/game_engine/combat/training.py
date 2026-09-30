"""Config-driven generic enemy pack used by previews (no zone content required)."""

from pydantic import BaseModel, ConfigDict, Field

from app.game_engine.combat.models import CombatantSnapshot


class TrainingEncounter(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    count: int = Field(ge=1, le=10)
    hp_base: float = Field(ge=1)
    hp_per_level: float = Field(ge=0)
    attack_base: float = Field(ge=0)
    attack_per_level: float = Field(ge=0)
    armor_per_level: float = Field(ge=0)
    magic_resist_per_level: float = Field(ge=0)
    accuracy: float = Field(ge=0, le=200)
    dodge: float = Field(ge=0, le=100)
    crit_chance: float = Field(ge=0, le=100)


def training_pack(
    cfg: TrainingEncounter, level: int, *, power_percent: float = 100.0, count: int | None = None
) -> tuple[CombatantSnapshot, ...]:
    mult = power_percent / 100.0
    stats = {
        "max_hp": (cfg.hp_base + cfg.hp_per_level * level) * mult,
        "attack_power": (cfg.attack_base + cfg.attack_per_level * level) * mult,
        "armor": cfg.armor_per_level * level,
        "magic_resist": cfg.magic_resist_per_level * level,
        "accuracy": cfg.accuracy,
        "dodge": cfg.dodge,
        "crit_chance": cfg.crit_chance,
        "crit_damage": 150,
        "attack_speed": 100,
    }
    return tuple(
        CombatantSnapshot(id=f"t{i}", code="training_foe", side="enemies", level=level, stats=stats)
        for i in range(count or cfg.count)
    )
