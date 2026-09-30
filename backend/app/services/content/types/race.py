"""Race content type: localized identity, informational affinity, validated effects, balance validator."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.game_engine.effects import EffectValidationError, validate_effects
from app.game_engine.race_balance import RaceBalanceConfig, estimate_combat_advantage
from app.models.race import Race
from app.services.content.registry import ContentType, Issue, register
from app.services.content.types.balance import BALANCE_SCHEMAS, get_published_balance

BALANCE_SCHEMAS["race_balance"] = RaceBalanceConfig


class RaceData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sort_order: int = Field(ge=0, le=1000)
    identity: str = Field(max_length=32, pattern=r"^[a-z_]+$")
    trait_name_key: str = Field(max_length=200)
    trait_description_key: str = Field(max_length=200)
    title_key: str = Field(max_length=200)
    affinity: list[str] = Field(default_factory=list, max_length=20)
    effects: list[dict[str, Any]] = Field(default_factory=list, max_length=16)


async def validate_race(db: AsyncSession, code: str, data: dict[str, Any]) -> list[Issue]:
    try:
        validate_effects(data["effects"])
    except EffectValidationError as exc:
        return [Issue("error", "invalid_effect", exc.message, exc.path)]
    cfg = await get_published_balance(db, "race_balance", RaceBalanceConfig)
    total, _ = estimate_combat_advantage(cfg, data["effects"])
    if total > cfg.error_percent:
        return [
            Issue(
                "error",
                "race_overpowered",
                f"Estimated racial combat advantage {total:.1f}% exceeds {cfg.error_percent}%",
                "effects",
            )
        ]
    if total > cfg.warn_percent:
        return [
            Issue(
                "warning",
                "race_strong",
                f"Estimated racial combat advantage {total:.1f}% exceeds {cfg.warn_percent}%",
                "effects",
            )
        ]
    return []


RACE_TYPE = register(
    ContentType(
        entity_type="race",
        model=Race,
        data_schema=RaceData,
        l10n_prefix="race",
        validators=(validate_race,),
        public=True,
    )
)
