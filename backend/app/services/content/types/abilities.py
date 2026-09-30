"""Content types: abilities, talent trees/nodes, awakenings, masteries (+ publish validators)."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.game_engine.effects import EffectValidationError, validate_effects
from app.game_engine.talents import NodeDef, TalentConfig, validate_tree_graph
from app.models.abilities import AbilityDefinition, AwakeningDefinition, MasteryDefinition, TalentNode, TalentTree
from app.models.classes import BaseClass, ClassBranch, Specialization
from app.services.content.registry import ContentType, Issue, register
from app.services.content.types.balance import BALANCE_SCHEMAS, get_published_balance


class _S(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AbilityLimits(_S):
    max_core_actives: int = Field(ge=1, le=20)
    max_ultimates: int = Field(ge=0, le=5)
    max_passives: int = Field(ge=0, le=100)


BALANCE_SCHEMAS["talents"] = TalentConfig
BALANCE_SCHEMAS["ability_limits"] = AbilityLimits


class Cost(_S):
    resource: str = Field(pattern=r"^[a-z_]+$")
    amount: float = Field(gt=0, le=1000)


class Rank(_S):
    rank: int = Field(ge=1, le=10)
    cost: Cost | None = None
    cooldown_s: float = Field(ge=0, le=3600, default=0)
    cast_time_s: float = Field(ge=0, le=60, default=0)
    effects: list[dict[str, Any]] = Field(min_length=1, max_length=16)


class AbilityData(_S):
    owner_type: str = Field(pattern=r"^(class|branch|specialization|global)$")
    owner_code: str | None = None
    ability_type: str = Field(pattern=r"^(ACTIVE|PASSIVE|ULTIMATE|STANCE|AURA|PROC)$")
    unlock_level: int = Field(ge=1, le=1000)
    target_rule: str = Field(pattern=r"^(self|enemy_single|enemy_all|lowest_hp_ally|party)$")
    tags: list[str] = Field(default_factory=list, max_length=12)
    ranks: list[Rank] = Field(min_length=1, max_length=10)
    trigger: str | None = Field(default=None, max_length=32)
    sort_order: int = Field(ge=0, le=1000, default=0)


class TreeData(_S):
    base_class_code: str
    focus_key: str = Field(max_length=200)
    sort_order: int = Field(ge=0, le=10)


class NodeData(_S):
    tree_code: str
    tier: int = Field(ge=1, le=6)
    slot: str = Field(max_length=16)
    max_rank: int = Field(ge=1, le=10)
    required_points_in_tree: int = Field(ge=0, le=100)
    required_level: int = Field(ge=1, le=1000)
    is_capstone: bool = False
    requires: list[str] = Field(default_factory=list, max_length=4)
    archetype_key: str | None = Field(default=None, max_length=200)
    effects: list[dict[str, Any]] = Field(min_length=1, max_length=8)


class AwakeningData(_S):
    specialization_code: str
    required_level: int = Field(ge=1, le=1000)
    effects: list[dict[str, Any]] = Field(min_length=1, max_length=8)


class MasteryData(_S):
    base_class_code: str
    required_level: int = Field(ge=1, le=1000)
    cosmetic_code: str = Field(max_length=96)
    effects: list[dict[str, Any]] = Field(min_length=1, max_length=8)


def _effects(effects: list[dict[str, Any]], path: str) -> list[Issue]:
    try:
        validate_effects(effects, path)
    except EffectValidationError as exc:
        return [Issue("error", "invalid_effect", exc.message, exc.path)]
    return []


async def _exists(db: AsyncSession, model: Any, code: str | None) -> bool:
    if code is None:
        return False
    return (
        await db.execute(select(model.id).where(model.code == code, model.deleted_at.is_(None)))
    ).first() is not None


OWNER_MODELS = {"class": BaseClass, "branch": ClassBranch, "specialization": Specialization}


async def spec_ability_counts(
    db: AsyncSession, spec_code: str, extra: dict[str, Any] | None = None, exclude_code: str | None = None
) -> dict[str, int]:
    """Count abilities available to a specialization (its class + branch + spec owners)."""
    spec = (await db.execute(select(Specialization).where(Specialization.code == spec_code))).scalar_one()
    branch = (await db.execute(select(ClassBranch).where(ClassBranch.code == spec.branch_code))).scalar_one()
    owners = {("class", branch.base_class_code), ("branch", branch.code), ("specialization", spec.code)}
    rows = (
        await db.execute(
            select(
                AbilityDefinition.code,
                AbilityDefinition.owner_type,
                AbilityDefinition.owner_code,
                AbilityDefinition.ability_type,
            ).where(AbilityDefinition.deleted_at.is_(None), AbilityDefinition.status != "archived")
        )
    ).all()
    counts: dict[str, int] = {}
    for code, otype, ocode, atype in rows:
        if code != exclude_code and (otype, ocode) in owners:
            counts[atype] = counts.get(atype, 0) + 1
    if extra and (extra["owner_type"], extra["owner_code"]) in owners:
        counts[extra["ability_type"]] = counts.get(extra["ability_type"], 0) + 1
    return counts


async def validate_ability(db: AsyncSession, code: str, d: dict[str, Any]) -> list[Issue]:
    issues: list[Issue] = []
    for i, r in enumerate(d["ranks"]):
        issues += _effects(r["effects"], f"ranks[{i}].effects")
    if d["owner_type"] != "global" and not await _exists(db, OWNER_MODELS[d["owner_type"]], d["owner_code"]):
        issues.append(Issue("error", "unknown_reference", "unknown owner", "owner_code"))
        return issues
    limits = await get_published_balance(db, "ability_limits", AbilityLimits)
    if d["ability_type"] in ("ACTIVE", "ULTIMATE"):
        spec_codes: list[str] = []
        if d["owner_type"] == "specialization":
            spec_codes = [d["owner_code"]]
        elif d["owner_type"] == "branch":
            spec_codes = list(
                (
                    await db.execute(select(Specialization.code).where(Specialization.branch_code == d["owner_code"]))
                ).scalars()
            )
        elif d["owner_type"] == "class":
            spec_codes = list(
                (
                    await db.execute(
                        select(Specialization.code)
                        .join(ClassBranch, ClassBranch.code == Specialization.branch_code)
                        .where(ClassBranch.base_class_code == d["owner_code"])
                    )
                ).scalars()
            )
        for sc in spec_codes:
            counts = await spec_ability_counts(db, sc, d, exclude_code=code)
            if counts.get("ACTIVE", 0) > limits.max_core_actives:
                issues.append(
                    Issue(
                        "error",
                        "too_many_actives",
                        f"{sc} would have {counts['ACTIVE']} actives (max {limits.max_core_actives})",
                    )
                )
            if counts.get("ULTIMATE", 0) > limits.max_ultimates:
                issues.append(
                    Issue(
                        "error",
                        "too_many_ultimates",
                        f"{sc} would have {counts['ULTIMATE']} ultimates (max {limits.max_ultimates})",
                    )
                )
    return issues


async def validate_tree(db: AsyncSession, code: str, d: dict[str, Any]) -> list[Issue]:
    if not await _exists(db, BaseClass, d["base_class_code"]):
        return [Issue("error", "unknown_reference", "unknown class", "base_class_code")]
    cfg = await get_published_balance(db, "talents", TalentConfig)
    siblings = (
        await db.execute(
            select(func.count())
            .select_from(TalentTree)
            .where(
                TalentTree.base_class_code == d["base_class_code"],
                TalentTree.code != code,
                TalentTree.deleted_at.is_(None),
                TalentTree.status != "archived",
            )
        )
    ).scalar_one()
    if siblings >= cfg.trees_per_class:
        return [Issue("error", "too_many_trees", f"a class has exactly {cfg.trees_per_class} talent trees")]
    return []


async def validate_node(db: AsyncSession, code: str, d: dict[str, Any]) -> list[Issue]:
    issues = _effects(d["effects"], "effects")
    if not await _exists(db, TalentTree, d["tree_code"]):
        return [*issues, Issue("error", "unknown_reference", "unknown tree", "tree_code")]
    cfg = await get_published_balance(db, "talents", TalentConfig)
    rows = list(
        (
            await db.execute(
                select(TalentNode).where(
                    TalentNode.tree_code == d["tree_code"],
                    TalentNode.deleted_at.is_(None),
                    TalentNode.status != "archived",
                    TalentNode.code != code,
                )
            )
        ).scalars()
    )
    defs = [
        NodeDef(
            n.code,
            n.tree_code,
            n.tier,
            n.max_rank,
            n.required_points_in_tree,
            n.required_level,
            n.is_capstone,
            tuple(n.requires),
        )
        for n in rows
    ]
    defs.append(
        NodeDef(
            code,
            d["tree_code"],
            d["tier"],
            d["max_rank"],
            d["required_points_in_tree"],
            d["required_level"],
            d["is_capstone"],
            tuple(d["requires"]),
        )
    )
    for problem, node, message in validate_tree_graph(defs, cfg):
        if node in (code, d["tree_code"]) or problem in ("circular_dependency", "duplicate_capstone"):
            issues.append(Issue("error", problem, message, node))
    return issues


async def validate_awakening(db: AsyncSession, code: str, d: dict[str, Any]) -> list[Issue]:
    issues = _effects(d["effects"], "effects")
    if not await _exists(db, Specialization, d["specialization_code"]):
        issues.append(Issue("error", "unknown_reference", "unknown specialization", "specialization_code"))
    return issues


async def validate_mastery(db: AsyncSession, code: str, d: dict[str, Any]) -> list[Issue]:
    issues = _effects(d["effects"], "effects")
    if not await _exists(db, BaseClass, d["base_class_code"]):
        issues.append(Issue("error", "unknown_reference", "unknown class", "base_class_code"))
    return issues


ABILITY_TYPE = register(
    ContentType("ability", AbilityDefinition, AbilityData, "ability", validators=(validate_ability,), public=True)
)
TALENT_TREE_TYPE = register(
    ContentType("talent_tree", TalentTree, TreeData, "talent_tree", validators=(validate_tree,), public=True)
)
TALENT_NODE_TYPE = register(
    ContentType("talent_node", TalentNode, NodeData, "talent_node", validators=(validate_node,), public=True)
)
AWAKENING_TYPE = register(
    ContentType(
        "awakening", AwakeningDefinition, AwakeningData, "awakening", validators=(validate_awakening,), public=True
    )
)
MASTERY_TYPE = register(
    ContentType("mastery", MasteryDefinition, MasteryData, "mastery", validators=(validate_mastery,), public=True)
)
