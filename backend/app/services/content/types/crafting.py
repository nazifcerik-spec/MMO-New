"""Gathering nodes, recipes and imbues (content) with publish validators."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.game_engine.crafting import CraftingConfig
from app.game_engine.effects import EffectValidationError, validate_effects
from app.game_engine.items import CATEGORIES, EQUIP_SLOTS, STACKABLE_CATEGORIES
from app.models.crafting import GatheringNode, ImbueDefinition, Recipe
from app.models.items import ItemTemplate
from app.models.professions import Profession
from app.services.content.registry import ContentType, Issue, register
from app.services.content.types.balance import BALANCE_SCHEMAS, get_published_balance

BALANCE_SCHEMAS["crafting"] = CraftingConfig
CODE = r"^[a-z0-9_]+$"


class _S(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NodeEntry(_S):
    template_code: str = Field(max_length=96, pattern=CODE)
    weight: float = Field(gt=0, le=100_000)
    min: int = Field(ge=1, le=1000)
    max: int = Field(ge=1, le=1000)
    rare: bool = False

    @model_validator(mode="after")
    def _r(self) -> "NodeEntry":
        if self.max < self.min:
            raise ValueError("max < min")
        return self


class GatheringNodeData(_S):
    profession_code: str = Field(max_length=96)
    tier: int = Field(ge=0, le=10)
    actions_per_hour: float | None = Field(default=None, gt=0, le=10_000)
    entries: list[NodeEntry] = Field(min_length=1, max_length=20)


class Ingredient(_S):
    template_code: str = Field(max_length=96, pattern=CODE)
    qty: int = Field(ge=1, le=10_000)


class Output(_S):
    template_code: str = Field(max_length=96, pattern=CODE)
    qty: int = Field(ge=1, le=1000)


class Unlock(_S):
    kind: Literal["auto", "scroll", "reputation", "exploration"]
    ref: str | None = Field(default=None, max_length=96)


class RecipeData(_S):
    profession_code: str = Field(max_length=96)
    required_level: int = Field(ge=1, le=500)
    recipe_rarity: Literal["common", "rare", "epic"] = "common"
    unlock: Unlock = Field(default_factory=lambda: Unlock(kind="auto"))
    scroll_template_code: str | None = Field(default=None, max_length=96)
    ingredients: list[Ingredient] = Field(min_length=1, max_length=8)
    tool_kind: str | None = Field(default=None, max_length=32, pattern=r"^[a-z_]+$")
    workstation: str | None = Field(default=None, max_length=32, pattern=r"^[a-z_]+$")
    craft_time_s: float = Field(gt=0, le=86_400)
    xp: int = Field(ge=0, le=100_000)
    output: Output
    quality_applies: bool = True
    fail_chance_pct: float = Field(default=0, ge=0, le=95)
    fail_return_pct: int = Field(default=50, ge=0, le=100)


class ImbueData(_S):
    required_level: int = Field(ge=1, le=500)
    categories: list[str] = Field(min_length=1, max_length=4)
    slots: list[str] = Field(default_factory=list, max_length=14)
    effects: list[dict[str, Any]] = Field(min_length=1, max_length=3)
    gold_cost: int = Field(default=0, ge=0, le=10**9)
    materials: list[Ingredient] = Field(default_factory=list, max_length=4)

    @model_validator(mode="after")
    def _c(self) -> "ImbueData":
        if any(c not in CATEGORIES for c in self.categories) or any(s not in EQUIP_SLOTS for s in self.slots):
            raise ValueError("unknown category or slot")
        return self


async def _template(db: AsyncSession, code: str) -> ItemTemplate | None:
    return (
        await db.execute(select(ItemTemplate).where(ItemTemplate.code == code, ItemTemplate.deleted_at.is_(None)))
    ).scalar_one_or_none()


async def _profession(db: AsyncSession, code: str) -> Profession | None:
    return (
        await db.execute(select(Profession).where(Profession.code == code, Profession.deleted_at.is_(None)))
    ).scalar_one_or_none()


async def validate_node(db: AsyncSession, code: str, d: dict[str, Any]) -> list[Issue]:
    issues: list[Issue] = []
    prof = await _profession(db, d["profession_code"])
    if prof is None or prof.type != "gathering":
        issues.append(Issue("error", "invalid_profession", "nodes belong to a gathering profession", "profession_code"))
    for i, e in enumerate(d["entries"]):
        t = await _template(db, e["template_code"])
        if t is None:
            issues.append(Issue("error", "unknown_reference", f"unknown item {e['template_code']}", f"entries[{i}]"))
        elif t.category not in STACKABLE_CATEGORIES:
            issues.append(Issue("error", "not_stackable", "gathering yields stackable materials", f"entries[{i}]"))
    return issues


async def validate_recipe(db: AsyncSession, code: str, d: dict[str, Any]) -> list[Issue]:
    issues: list[Issue] = []
    prof = await _profession(db, d["profession_code"])
    if prof is None or prof.type != "crafting":
        issues.append(
            Issue("error", "invalid_profession", "recipes belong to a crafting profession", "profession_code")
        )
    elif d["tool_kind"] and d["tool_kind"] != prof.tool_kind:
        issues.append(Issue("error", "invalid_tool", f"{prof.code} uses {prof.tool_kind}", "tool_kind"))
    for i, ing in enumerate(d["ingredients"]):
        t = await _template(db, ing["template_code"])
        if t is None:
            issues.append(
                Issue("error", "unknown_reference", f"unknown ingredient {ing['template_code']}", f"ingredients[{i}]")
            )
        elif t.stack_size < 2:
            issues.append(Issue("warning", "unique_ingredient", "ingredient is not stackable", f"ingredients[{i}]"))
    out = await _template(db, d["output"]["template_code"])
    if out is None:
        issues.append(Issue("error", "unknown_reference", "unknown output item", "output"))
    elif d["output"]["qty"] > out.stack_size:
        issues.append(Issue("error", "output_exceeds_stack", "output qty exceeds stack size", "output"))
    elif out.category not in STACKABLE_CATEGORIES and not d["quality_applies"]:
        issues.append(
            Issue("warning", "no_quality", "equipment outputs usually use crafting quality", "quality_applies")
        )
    if any(ing["template_code"] == d["output"]["template_code"] for ing in d["ingredients"]):
        issues.append(Issue("error", "circular_recipe", "output cannot be its own ingredient", "ingredients"))
    cfg = await get_published_balance(db, "crafting", CraftingConfig)
    if d["workstation"] and d["workstation"] not in cfg.workstations:
        issues.append(Issue("error", "unknown_reference", "unknown workstation", "workstation"))
    if d["unlock"]["kind"] == "scroll":
        scroll = await _template(db, d["scroll_template_code"] or "")
        if scroll is None or scroll.category != "recipe":
            issues.append(
                Issue(
                    "error", "unknown_reference", "scroll recipes need a recipe-category item", "scroll_template_code"
                )
            )
    elif d["recipe_rarity"] != "common" and d["unlock"]["kind"] == "auto":
        issues.append(
            Issue(
                "warning",
                "rare_recipe_auto",
                "rare/epic recipes usually come from drops/reputation/exploration",
                "unlock",
            )
        )
    return issues


async def validate_imbue(db: AsyncSession, code: str, d: dict[str, Any]) -> list[Issue]:
    try:
        validate_effects(d["effects"], "effects")
    except EffectValidationError as exc:
        return [Issue("error", "invalid_effect", exc.message, exc.path)]
    issues: list[Issue] = []
    for i, m in enumerate(d["materials"]):
        if await _template(db, m["template_code"]) is None:
            issues.append(Issue("error", "unknown_reference", "unknown material", f"materials[{i}]"))
    return issues


GATHERING_NODE_TYPE = register(
    ContentType(
        "gathering_node", GatheringNode, GatheringNodeData, "gathering_node", validators=(validate_node,), public=True
    )
)
RECIPE_TYPE = register(ContentType("recipe", Recipe, RecipeData, "recipe", validators=(validate_recipe,), public=True))
IMBUE_TYPE = register(
    ContentType("imbue", ImbueDefinition, ImbueData, "imbue", validators=(validate_imbue,), public=True)
)
