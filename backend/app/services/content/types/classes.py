"""Class content types (resources, weapon/armor families, base classes, branches, specializations)."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.game_engine.effects import EffectValidationError, validate_effects
from app.game_engine.stats import PRIMARY_STATS
from app.models.classes import ArmorFamily, BaseClass, ClassBranch, ClassResource, Specialization, WeaponFamily
from app.services.content.registry import ContentType, Issue, register
from app.services.content.types.balance import BALANCE_SCHEMAS

MAX_BRANCHES_PER_CLASS = 2
MAX_SPECS_PER_BRANCH = 2


class _S(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ClassPathConfig(_S):
    first_change_free: bool
    branch_change_gold_per_level: int = Field(ge=0)
    spec_change_gold_per_level: int = Field(ge=0)
    cooldown_hours: int = Field(ge=0, le=24 * 30)
    solo_accord_default_percent: float = Field(ge=0, le=100)


BALANCE_SCHEMAS["class_path"] = ClassPathConfig


class ResourceData(_S):
    max_value: float = Field(gt=0, le=10_000)
    start_value: float = Field(ge=0, le=10_000)
    regen_per_s: float = Field(ge=0, le=1000)
    decay_per_s: float = Field(ge=0, le=1000)


class WeaponFamilyData(_S):
    hands: int = Field(ge=1, le=2)
    kind: str = Field(pattern=r"^(melee|ranged|magic|instrument)$")


class ArmorFamilyData(_S):
    pass


class BaseClassData(_S):
    category: str = Field(pattern=r"^(combat|support)$")
    sort_order: int = Field(ge=0, le=1000)
    role_key: str = Field(max_length=200)
    primary_stat: str
    secondary_stat: str
    utility_stat: str
    main_damage_stat: str
    resources: list[str] = Field(min_length=1, max_length=4)
    weapon_families: list[str] = Field(min_length=1, max_length=30)
    armor_families: list[str] = Field(min_length=1, max_length=8)
    dual_wield: bool = False
    item_tags: list[str] = Field(min_length=1, max_length=4)
    base_passive_code: str = Field(max_length=96)
    base_effects: list[dict[str, Any]] = Field(max_length=16)
    solo_accord: dict[str, Any] | None = None


class BranchData(_S):
    base_class_code: str
    sort_order: int = Field(ge=0, le=1000)
    role_key: str = Field(max_length=200)
    passive_code: str = Field(max_length=96)
    effects: list[dict[str, Any]] = Field(max_length=16)


class SpecializationData(_S):
    branch_code: str
    sort_order: int = Field(ge=0, le=1000)
    role_key: str = Field(max_length=200)
    mastery_noun_key: str = Field(max_length=200)
    passive_code: str = Field(max_length=96)
    effects: list[dict[str, Any]] = Field(max_length=16)


def _effects_issues(effects: list[dict[str, Any]], path: str = "effects") -> list[Issue]:
    try:
        validate_effects(effects, path)
    except EffectValidationError as exc:
        return [Issue("error", "invalid_effect", exc.message, exc.path)]
    return []


async def _missing(db: AsyncSession, model: Any, codes: list[str]) -> list[str]:
    found: set[str] = set(
        (await db.execute(select(model.code).where(model.code.in_(codes), model.deleted_at.is_(None)))).scalars()
    )
    return sorted(set(codes) - found)


async def validate_base_class(db: AsyncSession, code: str, d: dict[str, Any]) -> list[Issue]:
    issues: list[Issue] = []
    for f in ("primary_stat", "secondary_stat", "utility_stat", "main_damage_stat"):
        if d[f] not in PRIMARY_STATS:
            issues.append(Issue("error", "invalid_stat", f"{d[f]} is not a primary stat", f))
    for field, model in (
        ("resources", ClassResource),
        ("weapon_families", WeaponFamily),
        ("armor_families", ArmorFamily),
    ):
        missing = await _missing(db, model, d[field])
        if missing:
            issues.append(Issue("error", "unknown_reference", f"unknown codes {missing}", field))
    issues += _effects_issues(d["base_effects"], "base_effects")
    if d["solo_accord"] is not None:
        issues += _effects_issues([{"effect_type": "SOLO_ACCORD", "params": d["solo_accord"]}], "solo_accord")
    if d["category"] == "support" and not d["solo_accord"]:
        issues.append(Issue("error", "solo_accord_required", "support classes need a Solo Accord conversion"))
    return issues


async def validate_branch(db: AsyncSession, code: str, d: dict[str, Any]) -> list[Issue]:
    issues = _effects_issues(d["effects"])
    if await _missing(db, BaseClass, [d["base_class_code"]]):
        issues.append(Issue("error", "unknown_reference", "unknown base class", "base_class_code"))
    siblings = (
        await db.execute(
            select(func.count())
            .select_from(ClassBranch)
            .where(
                ClassBranch.base_class_code == d["base_class_code"],
                ClassBranch.code != code,
                ClassBranch.deleted_at.is_(None),
                ClassBranch.status != "archived",
            )
        )
    ).scalar_one()
    if siblings >= MAX_BRANCHES_PER_CLASS:
        issues.append(Issue("error", "too_many_branches", "a base class has exactly two Lv100 paths"))
    return issues


async def validate_specialization(db: AsyncSession, code: str, d: dict[str, Any]) -> list[Issue]:
    issues = _effects_issues(d["effects"])
    if await _missing(db, ClassBranch, [d["branch_code"]]):
        issues.append(Issue("error", "unknown_reference", "unknown branch", "branch_code"))
    siblings = (
        await db.execute(
            select(func.count())
            .select_from(Specialization)
            .where(
                Specialization.branch_code == d["branch_code"],
                Specialization.code != code,
                Specialization.deleted_at.is_(None),
                Specialization.status != "archived",
            )
        )
    ).scalar_one()
    if siblings >= MAX_SPECS_PER_BRANCH:
        issues.append(Issue("error", "too_many_specializations", "a branch has exactly two Lv300 specializations"))
    return issues


RESOURCE_TYPE = register(ContentType("class_resource", ClassResource, ResourceData, "resource", public=True))
WEAPON_FAMILY_TYPE = register(
    ContentType("weapon_family", WeaponFamily, WeaponFamilyData, "weapon_family", public=True)
)
ARMOR_FAMILY_TYPE = register(ContentType("armor_family", ArmorFamily, ArmorFamilyData, "armor_family", public=True))
BASE_CLASS_TYPE = register(
    ContentType("base_class", BaseClass, BaseClassData, "class", validators=(validate_base_class,), public=True)
)
BRANCH_TYPE = register(
    ContentType("class_branch", ClassBranch, BranchData, "branch", validators=(validate_branch,), public=True)
)
SPECIALIZATION_TYPE = register(
    ContentType(
        "specialization", Specialization, SpecializationData, "spec", validators=(validate_specialization,), public=True
    )
)
