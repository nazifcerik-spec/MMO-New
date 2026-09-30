"""Talent allocation, reset, available abilities, awakening/mastery contributions (data-driven)."""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, ValidationFailedError
from app.game_engine.stat_calculator import Contribution, contribution_from_effects
from app.game_engine.talents import (
    NodeDef,
    TalentConfig,
    points_for_level,
    reset_quote,
    scale_effect,
    validate_allocation,
)
from app.localization.service import resolve_text_map
from app.models.abilities import (
    AbilityDefinition,
    AwakeningDefinition,
    CharacterTalentAllocation,
    MasteryDefinition,
    TalentNode,
    TalentTree,
)
from app.models.character import Character
from app.models.classes import ClassBranch
from app.services import audit, classes, progression, wallet
from app.services.content.types.balance import get_published_balance
from app.services.races import stat_label_keys

# Consumers able to remove materials from a character's inventory (registered by the inventory module).
MATERIAL_CONSUMERS: list[Any] = []


async def load_cfg(db: AsyncSession) -> TalentConfig:
    return await get_published_balance(db, "talents", TalentConfig)


async def class_trees(db: AsyncSession, class_code: str) -> tuple[list[TalentTree], list[TalentNode]]:
    trees = list(
        (
            await db.execute(
                select(TalentTree)
                .where(TalentTree.base_class_code == class_code, TalentTree.status == "published")
                .order_by(TalentTree.sort_order)
            )
        ).scalars()
    )
    nodes = list(
        (
            await db.execute(
                select(TalentNode)
                .where(TalentNode.tree_code.in_([t.code for t in trees]), TalentNode.status == "published")
                .order_by(TalentNode.tier, TalentNode.slot)
            )
        ).scalars()
    )
    return trees, nodes


def node_defs(nodes: list[TalentNode]) -> dict[str, NodeDef]:
    return {
        n.code: NodeDef(
            n.code,
            n.tree_code,
            n.tier,
            n.max_rank,
            n.required_points_in_tree,
            n.required_level,
            n.is_capstone,
            tuple(n.requires),
        )
        for n in nodes
    }


async def allocation(db: AsyncSession, character_id: int) -> dict[str, int]:
    rows = (
        await db.execute(
            select(CharacterTalentAllocation.node_code, CharacterTalentAllocation.rank).where(
                CharacterTalentAllocation.character_id == character_id
            )
        )
    ).all()
    return {code: rank for code, rank in rows}


async def talents_view(db: AsyncSession, character: Character, locale: str) -> dict[str, Any]:
    cfg = await load_cfg(db)
    row = await classes.get_progression_row(db, character)
    trees, nodes = await class_trees(db, row.base_class_code)
    alloc = await allocation(db, character.id)
    keys: set[str] = set()
    for t in trees:
        keys |= {t.name_key, t.focus_key}
    for n in nodes:
        keys |= {n.archetype_key or n.name_key}
        if n.is_capstone:
            keys.add(n.description_key or "")
        keys |= stat_label_keys(n.effects)
    text = await resolve_text_map(db, sorted(k for k in keys if k), locale)
    available = points_for_level(cfg, character.level)
    spent = sum(alloc.values())
    per_tree = {t.code: sum(alloc.get(n.code, 0) for n in nodes if n.tree_code == t.code) for t in trees}
    return {
        "character_id": character.id,
        "level": character.level,
        "points_available": available,
        "points_spent": spent,
        "points_remaining": max(0, available - spent),
        "total_max": cfg.points.total_max,
        "per_tree_max": cfg.points.per_tree_max,
        "capstone_level": cfg.capstone.required_level,
        "version": row.version,
        "reset_quote": reset_quote(cfg, character.level, spent),
        "trees": [
            {
                "code": t.code,
                "name": text[t.name_key],
                "focus": text[t.focus_key],
                "spent": per_tree[t.code],
                "nodes": [
                    {
                        "code": n.code,
                        "tier": n.tier,
                        "slot": n.slot,
                        "max_rank": n.max_rank,
                        "rank": alloc.get(n.code, 0),
                        "required_points_in_tree": n.required_points_in_tree,
                        "required_level": n.required_level,
                        "requires": n.requires,
                        "is_capstone": n.is_capstone,
                        "name": text[n.archetype_key or n.name_key],
                        "description": text.get(n.description_key or "") if n.is_capstone else None,
                        "effects": n.effects,
                    }
                    for n in nodes
                    if n.tree_code == t.code
                ],
            }
            for t in trees
        ],
        "labels": {k: v for k, v in text.items() if k.startswith("stat.")},
    }


async def apply_plan(
    db: AsyncSession, *, character: Character, plan: dict[str, int], expected_version: int, actor_id: int
) -> dict[str, int]:
    """Add talent ranks. Ranks can only increase (lowering requires a paid reset)."""
    cfg = await load_cfg(db)
    row = await classes.get_progression_row(db, character, for_update=True)
    if row.version != expected_version:
        raise ConflictError(
            "Talents changed elsewhere; reload", code="version_conflict", details={"current_version": row.version}
        )
    _, nodes = await class_trees(db, row.base_class_code)
    defs = node_defs(nodes)
    current = await allocation(db, character.id)
    merged = {**current, **{k: v for k, v in plan.items() if v}}
    for code, rank in plan.items():
        if not isinstance(rank, int) or isinstance(rank, bool):
            raise ValidationFailedError("Ranks must be integers", code="invalid_amount")
        if rank < current.get(code, 0):
            raise ValidationFailedError("Lowering a talent requires a reset", code="talent_decrease")
    errors = validate_allocation(defs, merged, character.level, cfg)
    if errors:
        raise ValidationFailedError(
            "Invalid talent allocation", code=errors[0][0], details=[{"code": c, "detail": d} for c, d in errors]
        )
    for code, rank in merged.items():
        if rank != current.get(code):
            await db.execute(
                insert(CharacterTalentAllocation)
                .values(character_id=character.id, node_code=code, rank=rank)
                .on_conflict_do_update(index_elements=["character_id", "node_code"], set_={"rank": rank})
            )
    row.talent_points_spent = sum(merged.values())
    await audit.record(
        db,
        actor_id=actor_id,
        action="talents.allocate",
        entity_type="character",
        entity_id=character.id,
        before=current,
        after=merged,
    )
    await db.flush()
    return merged


async def reset(db: AsyncSession, *, character: Character, idempotency_key: str, actor_id: int) -> dict[str, Any]:
    cfg = await load_cfg(db)
    row = await classes.get_progression_row(db, character, for_update=True)
    alloc = await allocation(db, character.id)
    spent = sum(alloc.values())
    if spent == 0:
        raise ValidationFailedError("No talents to reset", code="nothing_to_reset")
    quote = reset_quote(cfg, character.level, spent)
    if quote["material_code"] and quote["material_qty"]:
        if not MATERIAL_CONSUMERS:
            raise ConflictError("Material payments are not available yet", code="material_system_unavailable")
        for consume in MATERIAL_CONSUMERS:
            await consume(
                db, character, quote["material_code"], quote["material_qty"], f"talent_reset:{idempotency_key}"
            )
    if quote["gold"]:
        await wallet.change_gold(
            db,
            character_id=character.id,
            delta=-quote["gold"],
            reason="talent_reset",
            idempotency_key=f"talent_reset:{idempotency_key}",
            ref_type="character",
            ref_id=str(character.id),
        )
    await db.execute(delete(CharacterTalentAllocation).where(CharacterTalentAllocation.character_id == character.id))
    row.talent_resets += 1
    row.talent_points_spent = 0
    row.last_talent_reset_at = datetime.now(UTC)
    await audit.record(
        db,
        actor_id=actor_id,
        action="talents.reset",
        entity_type="character",
        entity_id=character.id,
        before=alloc,
        meta=quote,
    )
    await db.flush()
    return {"refunded_points": spent, **quote}


async def talent_contributions(db: AsyncSession, character: Character) -> list[Contribution]:
    alloc = await allocation(db, character.id)
    if not alloc:
        return []
    nodes = list((await db.execute(select(TalentNode).where(TalentNode.code.in_(list(alloc))))).scalars())
    effects: dict[str, list[dict[str, Any]]] = {}
    for n in nodes:
        effects.setdefault(n.tree_code, []).extend(scale_effect(e, alloc[n.code]) for e in n.effects)
    return [contribution_from_effects("talent", tree, eff) for tree, eff in effects.items()]


async def milestone_contributions(db: AsyncSession, character: Character) -> list[Contribution]:
    row = await classes.get_progression_row(db, character)
    out: list[Contribution] = []
    if row.awakened_at and row.specialization_code:
        aw = (
            await db.execute(
                select(AwakeningDefinition).where(
                    AwakeningDefinition.specialization_code == row.specialization_code,
                    AwakeningDefinition.status == "published",
                )
            )
        ).scalar_one_or_none()
        if aw:
            out.append(contribution_from_effects("class", aw.code, aw.effects))
    if row.mastery_at:
        m = (
            await db.execute(
                select(MasteryDefinition).where(
                    MasteryDefinition.base_class_code == row.base_class_code, MasteryDefinition.status == "published"
                )
            )
        ).scalar_one_or_none()
        if m:
            out.append(contribution_from_effects("class", m.code, m.effects))
    return out


async def available_abilities(db: AsyncSession, character: Character, locale: str) -> dict[str, Any]:
    row = await classes.get_progression_row(db, character)
    owners = [("class", row.base_class_code)]
    if row.branch_code:
        owners.append(("branch", row.branch_code))
    if row.specialization_code:
        owners.append(("specialization", row.specialization_code))
    abilities = list(
        (
            await db.execute(
                select(AbilityDefinition)
                .where(AbilityDefinition.status == "published")
                .order_by(AbilityDefinition.unlock_level, AbilityDefinition.sort_order)
            )
        ).scalars()
    )
    mine = [a for a in abilities if (a.owner_type, a.owner_code) in owners or a.owner_type == "global"]
    keys: set[str] = set()
    for a in mine:
        keys |= {a.name_key, a.description_key or ""}
        for r in a.ranks:
            keys |= stat_label_keys(r["effects"])
    awakening = None
    if row.specialization_code:
        awakening = (
            await db.execute(
                select(AwakeningDefinition).where(AwakeningDefinition.specialization_code == row.specialization_code)
            )
        ).scalar_one_or_none()
        if awakening:
            keys |= {awakening.name_key, awakening.description_key or ""}
    text = await resolve_text_map(db, sorted(k for k in keys if k), locale)
    return {
        "abilities": [
            {
                "code": a.code,
                "type": a.ability_type,
                "name": text[a.name_key],
                "description": text.get(a.description_key or ""),
                "unlock_level": a.unlock_level,
                "unlocked": character.level >= a.unlock_level,
                "target": a.target_rule,
                "tags": a.tags,
                "cost": a.ranks[0].get("cost"),
                "cooldown_s": a.ranks[0].get("cooldown_s", 0),
                "effects": a.ranks[0]["effects"],
                "trigger": a.trigger,
            }
            for a in mine
        ],
        "awakening": None
        if awakening is None
        else {
            "code": awakening.code,
            "name": text[awakening.name_key],
            "description": text.get(awakening.description_key or ""),
            "required_level": awakening.required_level,
            "active": row.awakened_at is not None,
            "effects": awakening.effects,
        },
        "labels": {k: v for k, v in text.items() if k.startswith("stat.")},
    }


async def branch_class(db: AsyncSession, branch_code: str) -> str:
    return (await db.execute(select(ClassBranch.base_class_code).where(ClassBranch.code == branch_code))).scalar_one()


progression.CONTRIBUTION_PROVIDERS.append(talent_contributions)
progression.CONTRIBUTION_PROVIDERS.append(milestone_contributions)
