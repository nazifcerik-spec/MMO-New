"""Quests (graph + promotion gates), achievements (aggregated counters), titles (selection + status rarity),
collections and prestige. Progress is driven by `events.emit` — one aggregated event per claim/action."""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError, ValidationFailedError
from app.game_engine import goals as rules
from app.localization.service import resolve_text_map
from app.models.character import Character
from app.models.classes import BaseClass
from app.models.content import ContentRevision
from app.models.items import ItemInstance, ItemProvenance, ItemTemplate
from app.models.professions import CharacterProfession, CharacterTitle
from app.models.quests import (
    Achievement,
    CharacterAchievement,
    CharacterCounter,
    CharacterQuest,
    CharacterTitleSelection,
    Quest,
)
from app.models.race import Race
from app.services import classes, events, inventory, progression, wallet, world
from app.services.content.types.balance import get_published_balance

GUILD_TITLE_PROVIDERS: list[Any] = []  # extension: async (db, character, locale) -> list[title dict]


def now_utc() -> datetime:
    return datetime.now(UTC)


async def config(db: AsyncSession) -> rules.GoalsConfig:
    return await get_published_balance(db, "goals", rules.GoalsConfig)


async def _quest_rev(db: AsyncSession, code: str, revision_no: int) -> dict[str, Any]:
    data: dict[str, Any] = (
        await db.execute(
            select(ContentRevision.data).where(
                ContentRevision.entity_type == "quest",
                ContentRevision.entity_code == code,
                ContentRevision.revision_no == revision_no,
            )
        )
    ).scalar_one()
    out: dict[str, Any] = data["data"]
    return out


async def _class_code(db: AsyncSession, character: Character) -> str:
    return str((await db.execute(select(BaseClass.code).where(BaseClass.id == character.base_class_id))).scalar_one())


# --------------------------------------------------------------------------- counters & achievements
async def bump(
    db: AsyncSession, character: Character, *, add: dict[str, int] | None = None, maxes: dict[str, int] | None = None
) -> list[str]:
    changed: list[str] = []
    for name, value in (add or {}).items():
        if value > 0:
            stmt = insert(CharacterCounter).values(character_id=character.id, counter=name, value=value)
            await db.execute(
                stmt.on_conflict_do_update(
                    index_elements=["character_id", "counter"], set_={"value": CharacterCounter.value + value}
                )
            )
            changed.append(name)
    for name, value in (maxes or {}).items():
        stmt = insert(CharacterCounter).values(character_id=character.id, counter=name, value=value)
        await db.execute(
            stmt.on_conflict_do_update(
                index_elements=["character_id", "counter"], set_={"value": func.greatest(CharacterCounter.value, value)}
            )
        )
        changed.append(name)
    if changed:
        await _check_achievements(db, character, changed)
    return changed


async def counters(db: AsyncSession, character_id: int) -> dict[str, int]:
    rows = await db.execute(
        select(CharacterCounter.counter, CharacterCounter.value).where(CharacterCounter.character_id == character_id)
    )
    return {c: int(v) for c, v in rows.all()}


async def _award_title(db: AsyncSession, character: Character, code: str, source: str) -> None:
    await db.execute(
        insert(CharacterTitle)
        .values(character_id=character.id, title_code=code, title_key=f"title.earned.{code}.name", source=source)
        .on_conflict_do_nothing(index_elements=["character_id", "title_code"])
    )


async def _check_achievements(db: AsyncSession, character: Character, changed: list[str]) -> list[str]:
    values = await counters(db, character.id)
    have = set(
        (
            await db.execute(
                select(CharacterAchievement.achievement_code).where(CharacterAchievement.character_id == character.id)
            )
        ).scalars()
    )
    rows = (
        await db.execute(
            select(Achievement).where(
                Achievement.counter.in_(changed), Achievement.status == "published", Achievement.deleted_at.is_(None)
            )
        )
    ).scalars()
    unlocked = []
    for a in rows:
        if a.code not in have and values.get(a.counter, 0) >= a.threshold:
            await db.execute(
                insert(CharacterAchievement)
                .values(character_id=character.id, achievement_code=a.code)
                .on_conflict_do_nothing(index_elements=["character_id", "achievement_code"])
            )
            if a.title_code:
                await _award_title(db, character, a.title_code, "achievement")
            unlocked.append(a.code)
    return unlocked


# --------------------------------------------------------------------------- quests
async def _quest(db: AsyncSession, code: str) -> Quest:
    q = (
        await db.execute(
            select(Quest).where(Quest.code == code, Quest.status == "published", Quest.deleted_at.is_(None))
        )
    ).scalar_one_or_none()
    if q is None:
        raise NotFoundError("Quest not found", code="quest_not_found")
    return q


async def _rows(db: AsyncSession, character_id: int, *, for_update: bool = False) -> dict[str, CharacterQuest]:
    stmt = select(CharacterQuest).where(CharacterQuest.character_id == character_id)
    if for_update:
        stmt = stmt.with_for_update()
    return {r.quest_code: r for r in (await db.execute(stmt)).scalars()}


async def quest_claimed(db: AsyncSession, character: Character, code: str) -> bool:
    row = (await _rows(db, character.id)).get(code)
    return row is not None and (row.status == "claimed" or row.times_completed > 0)


async def _seed_progress(db: AsyncSession, character: Character, objectives: list[dict[str, Any]]) -> list[int]:
    prof = {
        p.profession_code: p.level
        for p in (
            await db.execute(select(CharacterProfession).where(CharacterProfession.character_id == character.id))
        ).scalars()
    }
    out = []
    for o in objectives:
        if o["kind"] == "level":
            out.append(min(character.level, o["level"]))
        elif o["kind"] == "profession":
            out.append(min(prof.get(o["profession"], 1), o["level"]))
        else:
            out.append(0)
    return out


async def accept(db: AsyncSession, *, character: Character, code: str) -> dict[str, Any]:
    q = await _quest(db, code)
    rows = await _rows(db, character.id, for_update=True)
    row = rows.get(code)
    if row is not None and row.status in ("active", "completed"):
        raise ConflictError("Quest already in progress", code="quest_active")
    if row is not None and row.status == "claimed" and not q.repeatable:
        raise ConflictError("Quest already completed", code="quest_done")
    missing = [
        p for p in q.prerequisites if not (rows.get(p) and (rows[p].status == "claimed" or rows[p].times_completed))
    ]
    if missing:
        raise ConflictError("Prerequisites not met", code="quest_locked", details={"missing": missing})
    if character.level < q.min_level:
        raise ConflictError(f"Requires level {q.min_level}", code="level_too_low")
    if q.class_codes and await _class_code(db, character) not in q.class_codes:
        raise ConflictError("Not available to your class", code="quest_class_restricted")
    cfg = await config(db)
    if sum(1 for r in rows.values() if r.status in ("active", "completed")) >= cfg.max_active_quests:
        raise ConflictError("Too many active quests", code="quest_log_full")
    data = await _quest_rev(db, code, q.revision_no)
    progress = await _seed_progress(db, character, data["objectives"])
    status = "completed" if _auto_complete(data["objectives"], progress) else "active"
    if row is None:
        row = CharacterQuest(
            character_id=character.id,
            quest_code=code,
            quest_revision_no=q.revision_no,
            status=status,
            progress=progress,
        )
        db.add(row)
    else:
        row.quest_revision_no, row.status, row.progress = q.revision_no, status, progress
        row.accepted_at, row.completed_at, row.claimed_at, row.claim_key = now_utc(), None, None, None
    if status == "completed":
        row.completed_at = now_utc()
    await db.flush()
    await events.emit(db, character, "quest_accepted", {"quest": code})
    return {"quest": code, "status": row.status, "progress": row.progress}


def _auto_complete(objectives: list[dict[str, Any]], progress: list[int]) -> bool:
    if any(o["kind"] == "collect" for o in objectives):
        return False
    return rules.complete(objectives, progress, collected={})


async def abandon(db: AsyncSession, *, character: Character, code: str) -> None:
    row = (await _rows(db, character.id, for_update=True)).get(code)
    if row is None or row.status not in ("active", "completed"):
        raise NotFoundError("Quest not active", code="quest_not_active")
    row.status = "abandoned"
    await db.flush()


async def _collected(db: AsyncSession, character: Character, objectives: list[dict[str, Any]]) -> dict[str, int]:
    from app.services import crafting

    out = {}
    for o in objectives:
        if o["kind"] == "collect":
            out[o["template_code"]] = await crafting.count_in_bag(db, character.id, o["template_code"])
    return out


async def claim(db: AsyncSession, *, character: Character, code: str, key: str) -> dict[str, Any]:
    from app.services import crafting

    row = (await _rows(db, character.id, for_update=True)).get(code)
    if row is None:
        raise NotFoundError("Quest not accepted", code="quest_not_active")
    if row.status == "claimed":
        if row.claim_key == key:
            return {"quest": code, "replayed": True}
        raise ConflictError("Quest already claimed", code="quest_done")
    if row.status not in ("active", "completed"):
        raise ConflictError("Quest not active", code="quest_not_active")
    data = await _quest_rev(db, code, row.quest_revision_no)
    if not rules.complete(
        data["objectives"], row.progress, collected=await _collected(db, character, data["objectives"])
    ):
        raise ConflictError("Objectives not complete", code="quest_incomplete", details={"progress": row.progress})
    n = row.times_completed
    base = f"quest:{code}:{n}"
    for o in data["objectives"]:
        if o["kind"] == "collect":
            await crafting.consume(db, character, o["template_code"], o["count"], f"{base}:{character.id}:collect")
    r = data["rewards"]
    out: dict[str, Any] = {
        "quest": code,
        "xp": None,
        "gold": r.get("gold", 0),
        "items": [],
        "title": r.get("title_code"),
    }
    if r.get("xp"):
        out["xp"] = await progression.grant_xp(
            db, character=character, amount=r["xp"], idempotency_key=base, source_type="quest", source_id=code
        )
    if r.get("gold"):
        await wallet.change_gold(
            db,
            character_id=character.id,
            delta=r["gold"],
            reason="quest_reward",
            idempotency_key=base,
            ref_type="quest",
            ref_id=code,
        )
    for it in r.get("items", []):
        out["items"] += await inventory.add_item(
            db, character=character, template_code=it["template_code"], quantity=it["qty"], source_type="quest",
            source_id=code, key=f"{base}:{character.id}:{it['template_code']}",
        )  # fmt: skip
    if r.get("title_code"):
        await _award_title(db, character, r["title_code"], "quest")
    row.status, row.claim_key, row.claimed_at = "claimed", key, now_utc()
    row.completed_at = row.completed_at or row.claimed_at
    row.times_completed = n + 1
    await db.flush()
    await bump(db, character, add={"quests_completed": 1})
    return {**out, "replayed": False}


async def quest_log(db: AsyncSession, character: Character, locale: str) -> dict[str, Any]:
    quests = list(
        (
            await db.execute(
                select(Quest)
                .where(Quest.status == "published", Quest.deleted_at.is_(None))
                .order_by(Quest.min_level, Quest.code)
            )
        ).scalars()
    )
    rows = await _rows(db, character.id)
    cls = await _class_code(db, character)
    text = await resolve_text_map(db, [q.name_key for q in quests], locale)
    done = {c for c, r in rows.items() if r.status == "claimed" or r.times_completed}
    out: dict[str, list[dict[str, Any]]] = {"available": [], "active": [], "completed": [], "locked": []}
    for q in quests:
        row = rows.get(q.code)
        objectives = (await _quest_rev(db, q.code, row.quest_revision_no))["objectives"] if row else q.objectives
        progress: list[int] = list(row.progress) if row else [0] * len(objectives)
        view: dict[str, Any] = {
            "code": q.code, "name": text[q.name_key], "type": q.quest_type, "chain": q.chain, "min_level": q.min_level,
            "prerequisites": q.prerequisites, "objectives": objectives, "rewards": q.rewards,
            "repeatable": q.repeatable, "progress": progress, "status": row.status if row else None,
        }  # fmt: skip
        if row and row.status in ("active", "completed"):
            if any(o["kind"] == "collect" for o in objectives):
                coll = await _collected(db, character, objectives)
                view["progress"] = [
                    min(coll.get(o.get("template_code") or "", 0), o["count"]) if o["kind"] == "collect" else p
                    for o, p in zip(objectives, view["progress"], strict=False)
                ]
            out["active"].append(view)
        elif row and row.status == "claimed" and not q.repeatable:
            out["completed"].append(view)
        elif (
            all(p in done for p in q.prerequisites)
            and character.level >= q.min_level
            and (not q.class_codes or cls in q.class_codes)
        ):
            out["available"].append(view)
        else:
            out["locked"].append(view)
    return out


async def on_event(db: AsyncSession, character: Character, event: str, data: dict[str, Any]) -> None:
    """Aggregate one gameplay event into counters (achievements) and active quest progress."""
    if event == "afk_claimed":
        await bump(db, character, add={"kills": int(data.get("kills", 0)), "boss_kills": int(data.get("boss_kills", 0)),
                                       "afk_sessions": 1, "gold_earned": max(0, int(data.get("gold", 0)))})  # fmt: skip
    elif event == "level":
        await bump(db, character, maxes={"max_level": int(data["level"])})
    elif event == "profession_level":
        await bump(db, character, maxes={"max_profession_level": int(data["level"])})
    elif event == "action" and data.get("action") in ("craft_item", "trade"):
        await bump(
            db, character, add={{"craft_item": "crafts", "trade": "trades"}[data["action"]]: int(data.get("count", 1))}
        )
    if event not in ("afk_claimed", "level", "profession_level", "action"):
        return
    active = [r for r in (await _rows(db, character.id, for_update=True)).values() if r.status == "active"]
    for row in active:
        objectives = (await _quest_rev(db, row.quest_code, row.quest_revision_no))["objectives"]
        new = rules.apply_event(objectives, row.progress, event, data)
        if new != row.progress:
            row.progress = new
            if _auto_complete(objectives, new):
                row.status, row.completed_at = "completed", now_utc()
    await db.flush()


async def promotion_gate(db: AsyncSession, character: Character, stage: str, required: str | None) -> None:
    cfg = await config(db)
    code = required or (cfg.promotion_quests.get(stage) if cfg.promotion_quest_required.get(stage) else None)
    if code and not await quest_claimed(db, character, code):
        raise ConflictError(
            "Complete the promotion quest first", code="promotion_quest_required", details={"quest": code}
        )


# --------------------------------------------------------------------------- titles, collections, prestige
async def titles(db: AsyncSession, character: Character, locale: str) -> dict[str, Any]:
    cfg = await config(db)
    prog_cfg = await progression.load_config(db)
    ladder = [t for t in prog_cfg.titles if t.level <= character.level]
    race = await db.get(Race, character.race_id)
    row = await classes.get_progression_row(db, character)
    stage = (
        "eternal" if row.mastery_at else "ascendant" if row.capstone_unlocked_at else "awakened" if row.awakened_at
        else "specialization" if row.specialization_code else "branch" if row.branch_code else "base"
    )  # fmt: skip
    earned = list(
        (
            await db.execute(
                select(CharacterTitle)
                .where(CharacterTitle.character_id == character.id)
                .order_by(CharacterTitle.earned_at)
            )
        ).scalars()
    )
    ach_rarity = dict(
        (
            await db.execute(
                select(Achievement.title_code, Achievement.status_rarity).where(Achievement.title_code.is_not(None))
            )
        ).all()
    )
    keys = (
        [f"title.level.{t.code}.name" for t in ladder]
        + [t.title_key for t in earned]
        + ([race.title_key] if race else [])
    )
    text = await resolve_text_map(db, keys, locale)
    class_title = (await classes.class_view(db, character, locale))["class_title"]
    items = [
        {
            "ref": f"level:{t.code}",
            "kind": "level",
            "name": text[f"title.level.{t.code}.name"],
            "rarity": rules.level_rarity(cfg, t.level),
        }
        for t in ladder
    ]
    items.append(
        {"ref": "class", "kind": "class", "name": class_title, "rarity": cfg.class_stage_rarity.get(stage, "bronze")}
    )
    if race:
        items.append({"ref": "race", "kind": "race", "name": text[race.title_key], "rarity": cfg.race_title_rarity})
    for t in earned:
        rarity = {"profession": cfg.profession_title_rarity, "quest": cfg.quest_title_rarity}.get(
            t.source
        ) or ach_rarity.get(t.title_code, "silver")
        items.append({"ref": f"earned:{t.title_code}", "kind": t.source, "name": text[t.title_key], "rarity": rarity})
    for provider in GUILD_TITLE_PROVIDERS:
        items += await provider(db, character, locale)
    sel = await db.get(CharacterTitleSelection, character.id)
    refs = {i["ref"] for i in items}
    selected = (
        sel.title_ref if sel and sel.title_ref in refs else (items[len(ladder) - 1]["ref"] if ladder else "class")
    )
    return {"selected": selected, "titles": items}


async def select_title(db: AsyncSession, *, character: Character, ref: str) -> dict[str, Any]:
    view = await titles(db, character, "en")
    if ref not in {t["ref"] for t in view["titles"]}:
        raise ValidationFailedError("Title not available", code="title_unavailable")
    await db.execute(
        insert(CharacterTitleSelection)
        .values(character_id=character.id, title_ref=ref)
        .on_conflict_do_update(index_elements=["character_id"], set_={"title_ref": ref, "updated_at": func.now()})
    )
    return {"selected": ref}


async def achievements_view(db: AsyncSession, character: Character, locale: str) -> dict[str, Any]:
    cfg = await config(db)
    values = await counters(db, character.id)
    unlocked = dict(
        (
            await db.execute(
                select(CharacterAchievement.achievement_code, CharacterAchievement.unlocked_at).where(
                    CharacterAchievement.character_id == character.id
                )
            )
        ).all()
    )
    rows = list(
        (
            await db.execute(
                select(Achievement)
                .where(Achievement.status == "published", Achievement.deleted_at.is_(None))
                .order_by(Achievement.category, Achievement.threshold)
            )
        ).scalars()
    )
    text = await resolve_text_map(db, [a.name_key for a in rows], locale)
    points = sum(a.points for a in rows if a.code in unlocked)
    items = [
        {
            "code": a.code,
            "name": text[a.name_key],
            "category": a.category,
            "counter": a.counter,
            "threshold": a.threshold,
            "value": min(values.get(a.counter, 0), a.threshold),
            "rarity": a.status_rarity,
            "points": a.points,
            "title_code": a.title_code,
            "unlocked_at": unlocked[a.code].isoformat() if a.code in unlocked else None,
        }
        for a in rows
    ]
    return {
        "achievements": items,
        "counters": values,
        "points": points,
        "prestige": rules.prestige(cfg, points, character.mastery_xp),
    }


async def collections(db: AsyncSession, character: Character, locale: str) -> dict[str, Any]:
    tpls = list(
        (
            await db.execute(
                select(ItemTemplate)
                .where(ItemTemplate.category == "cosmetic_collectible", ItemTemplate.status == "published")
                .order_by(ItemTemplate.tier, ItemTemplate.code)
                .limit(500)
            )
        ).scalars()
    )
    owned = set(
        (
            await db.execute(
                select(ItemInstance.template_code)
                .join(ItemProvenance, ItemProvenance.instance_id == ItemInstance.id)
                .where(
                    ItemProvenance.character_id == character.id,
                    ItemProvenance.event == "created",
                    ItemInstance.template_code.in_([t.code for t in tpls]),
                )
                .distinct()
            )
        ).scalars()
    )
    text = await resolve_text_map(db, [f"item.{t.code}.name" for t in tpls], locale)
    groups: dict[str, list[dict[str, Any]]] = {}
    for t in tpls:
        groups.setdefault(t.family or "misc", []).append(
            {
                "template_code": t.code,
                "name": text[f"item.{t.code}.name"],
                "tier": t.tier,
                "rarity": t.rarity,
                "owned": t.code in owned,
            }
        )
    return {"total": len(tpls), "owned": len(owned), "groups": groups}


async def _on_level(db: AsyncSession, character: Character, res: Any) -> None:
    await events.emit(db, character, "level", {"level": character.level})


events.LISTENERS.append(on_event)
progression.POST_LEVEL_HOOKS.append(_on_level)
classes.QUEST_GATE_CHECKS.append(promotion_gate)


async def _quest_provider(db: AsyncSession, character: Character, code: str) -> bool:
    return await quest_claimed(db, character, code)


world.QUEST_PROVIDERS.append(_quest_provider)
