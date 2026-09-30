"""Profession content types + publish validators (canonical stats, exactly two specializations per profession,
specialization effects limited to PROFESSION_YIELD_MOD for their own profession)."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.game_engine.effects import EffectValidationError, validate_effects
from app.game_engine.professions import ProfessionConfig
from app.game_engine.stats import PRIMARY_STATS
from app.models.professions import Profession, ProfessionSpecialization
from app.services.content.registry import ContentType, Issue, register
from app.services.content.types.balance import BALANCE_SCHEMAS

BALANCE_SCHEMAS["professions"] = ProfessionConfig


class _S(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProfessionData(_S):
    type: Literal["gathering", "crafting", "service"]
    tool_kind: str = Field(max_length=32, pattern=r"^[a-z_]+$")
    stats: list[str] = Field(min_length=1, max_length=3)
    sort_order: int = Field(default=0, ge=0, le=1000)
    title_key: str = Field(max_length=200)
    effects: list[dict[str, Any]] = Field(default_factory=list, max_length=8)


class SpecializationData(_S):
    profession_code: str = Field(max_length=96)
    sort_order: int = Field(default=0, ge=0, le=10)
    effects: list[dict[str, Any]] = Field(min_length=1, max_length=6)


def _effects(effects: list[dict[str, Any]], path: str) -> list[Issue]:
    try:
        validate_effects(effects, path)
    except EffectValidationError as exc:
        return [Issue("error", "invalid_effect", exc.message, exc.path)]
    return []


async def validate_profession(db: AsyncSession, code: str, d: dict[str, Any]) -> list[Issue]:
    issues = _effects(d["effects"], "effects")
    bad = [s for s in d["stats"] if s not in PRIMARY_STATS]
    if bad:
        issues.append(Issue("error", "invalid_stat", f"unknown stats {bad}", "stats"))
    return issues


async def validate_specialization(db: AsyncSession, code: str, d: dict[str, Any]) -> list[Issue]:
    issues = _effects(d["effects"], "effects")
    prof = (
        await db.execute(
            select(Profession.id).where(Profession.code == d["profession_code"], Profession.deleted_at.is_(None))
        )
    ).first()
    if prof is None:
        return [*issues, Issue("error", "unknown_reference", "unknown profession", "profession_code")]
    for i, e in enumerate(d["effects"]):
        if e.get("effect_type") != "PROFESSION_YIELD_MOD" or e.get("params", {}).get("profession") not in (
            d["profession_code"],
            "*",
        ):
            issues.append(
                Issue(
                    "error",
                    "invalid_spec_effect",
                    "specializations may only modify their own profession",
                    f"effects[{i}]",
                )
            )
    siblings = (
        await db.execute(
            select(func.count())
            .select_from(ProfessionSpecialization)
            .where(
                ProfessionSpecialization.profession_code == d["profession_code"],
                ProfessionSpecialization.code != code,
                ProfessionSpecialization.deleted_at.is_(None),
                ProfessionSpecialization.status != "archived",
            )
        )
    ).scalar_one()
    if siblings >= 2:
        issues.append(Issue("error", "too_many_specializations", "each profession has exactly two specializations"))
    return issues


PROFESSION_TYPE = register(
    ContentType("profession", Profession, ProfessionData, "profession", validators=(validate_profession,), public=True)
)
PROFESSION_SPEC_TYPE = register(
    ContentType(
        "profession_specialization",
        ProfessionSpecialization,
        SpecializationData,
        "profession_spec",
        validators=(validate_specialization,),
        public=True,
    )
)
