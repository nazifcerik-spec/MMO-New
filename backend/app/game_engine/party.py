"""Pure party rules: size, role validation and capped composition bonuses."""

from collections import Counter
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.game_engine.effects import validate_effects

ROLES = ("tank", "healer", "support", "dps")


class _S(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ChatConfig(_S):
    max_length: int = Field(ge=1, le=2000)
    page_size: int = Field(ge=1, le=200)


class CompositionBonus(_S):
    code: str
    requires: dict[str, int]
    effects: tuple[dict[str, Any], ...] = Field(min_length=1)


class PartyConfig(_S):
    max_size: int = Field(ge=2, le=10)
    invite_ttl_minutes: int = Field(ge=1, le=1440)
    online_window_minutes: int = Field(ge=1, le=120)
    chat: ChatConfig
    enemy_power_pct_per_extra_member: float = Field(ge=0, le=300)
    role_options: dict[str, tuple[str, ...]]
    max_composition_bonuses: int = Field(ge=0, le=5)
    composition_bonuses: tuple[CompositionBonus, ...] = ()

    @model_validator(mode="after")
    def _check(self) -> "PartyConfig":
        for cls, roles in self.role_options.items():
            if not roles or any(r not in ROLES for r in roles):
                raise ValueError(f"invalid roles for {cls}")
        for b in self.composition_bonuses:
            if any(r not in ROLES or n < 1 for r, n in b.requires.items()):
                raise ValueError(f"invalid requirement in {b.code}")
            validate_effects(list(b.effects), f"composition_bonuses.{b.code}")
        return self


def default_role(cfg: PartyConfig, class_code: str) -> str:
    return cfg.role_options.get(class_code, ("dps",))[0]


def active_bonuses(cfg: PartyConfig, roles: list[str]) -> list[CompositionBonus]:
    """Bonuses whose role requirements are met, in config order, capped at `max_composition_bonuses`."""
    have = Counter(roles)
    met = [b for b in cfg.composition_bonuses if all(have[r] >= n for r, n in b.requires.items())]
    return met[: cfg.max_composition_bonuses]
