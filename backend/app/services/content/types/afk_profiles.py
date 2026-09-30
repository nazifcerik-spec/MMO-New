"""Passive profile content type + AFK-related balance schemas (risk profiles, training encounter)."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.game_engine.combat.rules import RuleValidationError, validate_rules
from app.game_engine.combat.training import TrainingEncounter
from app.game_engine.effects import EffectValidationError, validate_effects
from app.models.profiles import PassiveProfile
from app.services.content.registry import ContentType, Issue, register
from app.services.content.types.balance import BALANCE_SCHEMAS

RISK_LEVELS = ("safe", "balanced", "dangerous", "elite_hunt")
TARGET_PRIORITIES = ("first", "lowest_hp", "highest_hp", "elite_first", "boss_first", "healer_first")


class _S(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RiskProfile(_S):
    xp_loot_percent: int = Field(ge=1, le=300)
    enemy_power_percent: int = Field(ge=10, le=500)
    death_risk_percent: int = Field(ge=0, le=1000)
    consumption_percent: int = Field(ge=0, le=500)
    rare_bonus_percent: int = Field(ge=0, le=500)


class RiskProfiles(_S):
    profiles: dict[str, RiskProfile]
    default: Literal["safe", "balanced", "dangerous", "elite_hunt"]

    @model_validator(mode="after")
    def _canonical(self) -> "RiskProfiles":
        if set(self.profiles) != set(RISK_LEVELS):
            raise ValueError(f"risk profiles must be exactly {RISK_LEVELS}")
        return self


Mode = Literal["PASSIVE_ONLY", "ACTIVE_TACTICS", "HYBRID"]


class TemplateSlot(_S):
    tags: list[str] = Field(min_length=1, max_length=6)
    when: list[dict[str, Any]] = Field(default_factory=list, max_length=4)


class CombatModes(_S):
    default_mode: Mode
    enabled_modes: list[Mode] = Field(min_length=1)
    tactics_encounter_types: list[Literal["normal", "elite", "boss", "arena"]]
    max_rules: int = Field(ge=1, le=6)
    template: list[TemplateSlot] = Field(max_length=6)

    @model_validator(mode="after")
    def _check(self) -> "CombatModes":
        if self.default_mode not in self.enabled_modes:
            raise ValueError("default_mode must be enabled")
        validate_rules([{"use": {"tag": t.tags[0]}, "when": t.when} for t in self.template], max_rules=self.max_rules)
        return self


BALANCE_SCHEMAS["combat_modes"] = CombatModes


def template_rules(cfg: CombatModes, kit_tags: set[str]) -> list[dict[str, Any]]:
    """Instantiate the canonical priority template for a kit: first matching tag per slot, empty slots skipped."""
    out: list[dict[str, Any]] = []
    for slot in cfg.template:
        tag = next((t for t in slot.tags if t in kit_tags), None)
        if tag is not None:
            out.append({"use": {"tag": tag}, "when": slot.when})
    return out[: cfg.max_rules]


BALANCE_SCHEMAS["risk_profiles"] = RiskProfiles
BALANCE_SCHEMAS["training_encounter"] = TrainingEncounter


class ProfileDefaults(_S):
    stance: str = Field(max_length=32)
    target_priority: Literal["first", "lowest_hp", "highest_hp", "elite_first", "boss_first", "healer_first"]
    potion_threshold_pct: float = Field(ge=0, le=100)


class PassiveProfileData(_S):
    base_class_code: str
    sort_order: int = Field(default=0, ge=0, le=100)
    defaults: ProfileDefaults
    rules: list[dict[str, Any]] = Field(max_length=6)
    effects: list[dict[str, Any]] = Field(default_factory=list, max_length=8)


async def validate_profile(_db: Any, code: str, d: dict[str, Any]) -> list[Issue]:
    issues: list[Issue] = []
    try:
        validate_rules(d["rules"])
    except RuleValidationError as exc:
        issues.append(Issue("error", "invalid_rule", str(exc), "rules"))
    try:
        validate_effects(d["effects"])
    except EffectValidationError as exc:
        issues.append(Issue("error", "invalid_effect", exc.message, exc.path))
    return issues


PASSIVE_PROFILE_TYPE = register(
    ContentType(
        "passive_profile",
        PassiveProfile,
        PassiveProfileData,
        "passive_profile",
        validators=(validate_profile,),
        public=True,
    )
)
