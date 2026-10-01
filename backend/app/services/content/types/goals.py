"""Quest and achievement content types (validated, revisioned, localized)."""

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.game_engine.goals import AchievementData, GoalsConfig, QuestData, find_cycle
from app.models.classes import BaseClass
from app.models.items import ItemTemplate
from app.models.professions import Profession
from app.models.quests import Achievement, Quest
from app.models.world import Zone
from app.services.content.registry import ContentType, Issue, register
from app.services.content.types.balance import BALANCE_SCHEMAS

BALANCE_SCHEMAS["goals"] = GoalsConfig


async def _exists(db: AsyncSession, model: Any, code: str) -> bool:
    return (
        await db.execute(select(model.id).where(model.code == code, model.deleted_at.is_(None)))
    ).first() is not None


async def validate_quest(db: AsyncSession, code: str, d: dict[str, Any]) -> list[Issue]:
    issues: list[Issue] = []
    if code in d["prerequisites"]:
        issues.append(Issue("error", "self_prerequisite", "a quest cannot require itself", "prerequisites"))
    for i, p in enumerate(d["prerequisites"]):
        if not await _exists(db, Quest, p):
            issues.append(Issue("error", "unknown_reference", f"unknown prerequisite {p}", f"prerequisites[{i}]"))
    graph = {
        q.code: tuple(q.prerequisites)
        for q in (await db.execute(select(Quest).where(Quest.deleted_at.is_(None)))).scalars()
    }
    graph[code] = tuple(d["prerequisites"])
    cycle = find_cycle(graph)
    if cycle and code in cycle:
        issues.append(Issue("error", "prerequisite_cycle", " → ".join(cycle), "prerequisites"))
    for c in d["class_codes"]:
        if not await _exists(db, BaseClass, c):
            issues.append(Issue("error", "unknown_reference", f"unknown class {c}", "class_codes"))
    refs = {"zone": Zone, "template_code": ItemTemplate, "profession": Profession}
    for i, o in enumerate(d["objectives"]):
        for field, model in refs.items():
            if o.get(field) and not await _exists(db, model, o[field]):
                issues.append(
                    Issue("error", "unknown_reference", f"unknown {field} {o[field]}", f"objectives[{i}].{field}")
                )
    for i, it in enumerate(d["rewards"]["items"]):
        if not await _exists(db, ItemTemplate, it["template_code"]):
            issues.append(Issue("error", "unknown_reference", "unknown reward item", f"rewards.items[{i}]"))
    if d["quest_type"] == "promotion" and d["repeatable"]:
        issues.append(Issue("error", "promotion_repeatable", "promotion quests cannot repeat", "repeatable"))
    return issues


async def validate_achievement(db: AsyncSession, code: str, d: dict[str, Any]) -> list[Issue]:
    return []


QUEST_TYPE = register(ContentType("quest", Quest, QuestData, "quest", validators=(validate_quest,), public=True))
ACHIEVEMENT_TYPE = register(
    ContentType(
        "achievement", Achievement, AchievementData, "achievement", validators=(validate_achievement,), public=True
    )
)
