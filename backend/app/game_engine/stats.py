"""Stat vocabulary shared by content validation and the engine. Codes are immutable."""

from typing import Final, Literal

PRIMARY_STATS: Final[tuple[str, ...]] = ("STR", "DEX", "INT", "VIT", "WIS", "SPI", "LUK")
PrimaryStat = Literal["STR", "DEX", "INT", "VIT", "WIS", "SPI", "LUK"]

# Derived/combat stats that effects may modify. Values are computed by the stat calculator (Phase 05).
DERIVED_STATS: Final[tuple[str, ...]] = (
    "max_hp",
    "max_resource",
    "attack_power",
    "spell_power",
    "healing_power",
    "shield_power",
    "armor",
    "magic_resist",
    "elemental_resist",
    "accuracy",
    "dodge",
    "block",
    "block_efficiency",
    "crit_chance",
    "crit_damage",
    "attack_speed",
    "cast_speed",
    "resource_regen",
    "mana_regen",
    "hp_regen",
    "threat",
    "lifesteal",
    "armor_penetration",
    "magic_penetration",
    "buff_power",
    "debuff_power",
    "buff_duration",
    "debuff_duration",
    "hot_power",
    "pet_power",
    "totem_power",
    "stun_resist",
    "carry_capacity",
    "proc_consistency",
    "healing_received",
    "form_power",
    "song_power",
    "trap_power",
    "aura_power",
)

ALL_STATS: Final[frozenset[str]] = frozenset(PRIMARY_STATS + DERIVED_STATS)

DAMAGE_TYPES: Final[tuple[str, ...]] = (
    "physical",
    "magic",
    "true",
    "holy",
    "fire",
    "frost",
    "lightning",
    "nature",
    "poison",
    "shadow",
    "arcane",
)
