"""Game shell data: identity/resources summary, next meaningful goals and a localized-ready activity feed.

The activity feed is assembled from existing authoritative records (claimed AFK sessions, craft jobs, quests,
achievements, trades, profession level-ups); it adds no write path of its own."""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.game_engine import progression as prog
from app.game_engine.items import ItemRules
from app.localization.service import resolve_text_map
from app.models.afk import AfkSession
from app.models.character import Character
from app.models.crafting import CraftJob
from app.models.professions import CharacterProfession, ProfessionXpEvent
from app.models.progression import MarketListing
from app.models.quests import Achievement, CharacterAchievement, CharacterQuest, Quest
from app.models.world import Zone
from app.services import afk, classes, goals, progression, talents, wallet
from app.services.content.types.balance import get_published_balance

FEED_LIMIT = 30


async def summary(db: AsyncSession, character: Character, locale: str) -> dict[str, Any]:
    cfg = await progression.load_config(db)
    need = prog.xp_to_next(cfg, character.level)
    cls = await classes.class_view(db, character, locale)
    tv = await goals.titles(db, character, locale)
    shown = next((t for t in tv["titles"] if t["ref"] == tv["selected"]), None)
    tal = await talents.talents_view(db, character, locale)
    session = await afk.active_session(db, character.id)
    now = datetime.now(UTC)
    return {
        "character_id": character.id,
        "name": character.name,
        "level": character.level,
        "level_cap": cfg.level_cap,
        "xp": character.xp,
        "xp_to_next": need,
        "progress_percent": round(100 * character.xp / need, 2) if need else 100.0,
        "class_title": cls["class_title"],
        "title": shown,
        "gold": (await wallet.get_wallet(db, character.id)).gold,
        "unspent_stat_points": character.unspent_stat_points,
        "talent_points": tal["points_remaining"],
        "afk": None
        if session is None
        else {
            "zone_code": session.zone_code,
            "ends_at": session.ends_at.isoformat(),
            "claimable": afk.is_finished(session, now),
        },
        "next_goals": await next_goals(db, character, cls, tal, locale),
    }


async def next_goals(
    db: AsyncSession, character: Character, cls: dict[str, Any], tal: dict[str, Any], locale: str
) -> list[dict[str, Any]]:
    """Actionable items first, then the nearest level-gated milestones (title, class stage, item tier, zone)."""
    cfg = await progression.load_config(db)
    lvl = character.level
    out: list[dict[str, Any]] = []
    session = await afk.active_session(db, character.id)
    if session is not None and afk.is_finished(session, datetime.now(UTC)):
        out.append({"kind": "afk_claim"})
    if character.unspent_stat_points:
        out.append({"kind": "stat_points", "points": character.unspent_stat_points})
    if tal["points_remaining"]:
        out.append({"kind": "talent_points", "points": tal["points_remaining"]})
    stage = next((s for s in cls["stages"] if not s["completed_at"]), None)
    if stage and stage["unlocked"] and stage["stage"] in ("promotion", "specialization"):
        out.append({"kind": "class_stage_ready", "stage": stage["stage"], "name": stage["name"]})
    milestones: list[dict[str, Any]] = []
    nt = prog.next_title(cfg, lvl)
    if nt:
        text = await resolve_text_map(db, [f"title.level.{nt.code}.name"], locale)
        milestones.append({"kind": "level_title", "level": nt.level, "name": text[f"title.level.{nt.code}.name"]})
    if stage and not stage["unlocked"]:
        milestones.append(
            {"kind": "class_stage", "level": stage["min_level"], "stage": stage["stage"], "name": stage["name"]}
        )
    rules = await get_published_balance(db, "item_rules", ItemRules)
    tier = next((g for g in rules.tiers if g.min_level > lvl), None)
    if tier:
        milestones.append({"kind": "item_tier", "level": tier.min_level, "tier": tier.tier})
    zone = (
        await db.execute(
            select(Zone).where(Zone.status == "published", Zone.min_level > lvl).order_by(Zone.min_level).limit(1)
        )
    ).scalar_one_or_none()
    if zone:
        name = (await resolve_text_map(db, [zone.name_key], locale))[zone.name_key]
        milestones.append({"kind": "zone_unlock", "level": zone.min_level, "name": name})
    best = (
        await db.execute(
            select(CharacterProfession)
            .where(CharacterProfession.character_id == character.id)
            .order_by(CharacterProfession.level.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if best and best.level > 1:
        from app.services import professions

        pcfg = await professions.config(db)
        nxt = next((r for r in pcfg.ranks if r.min_level > best.level), None)
        if nxt:
            out.append(
                {
                    "kind": "profession_rank",
                    "profession": best.profession_code,
                    "level": nxt.min_level,
                    "rank": nxt.code,
                }
            )
    milestones.sort(key=lambda m: m["level"])
    return (out + milestones)[:5]


async def activity(db: AsyncSession, character: Character, locale: str) -> list[dict[str, Any]]:
    cid = character.id
    feed: list[dict[str, Any]] = []
    for s in (
        await db.execute(
            select(AfkSession)
            .where(AfkSession.character_id == cid, AfkSession.status == "claimed")
            .order_by(AfkSession.claimed_at.desc())
            .limit(FEED_LIMIT)
        )
    ).scalars():
        r = s.claim_result or {}
        feed.append(
            {
                "type": "afk_claimed",
                "at": s.claimed_at,
                "zone_code": s.zone_code,
                "xp": (r.get("result") or {}).get("xp", 0),
                "gold": r.get("gold", 0),
                "kills": (r.get("result") or {}).get("kills", 0),
                "signals": [
                    x for x in r.get("signals", []) if x.get("kind") in ("level_up", "rare_drops", "boss_kills")
                ],
            }
        )
    for j in (
        await db.execute(
            select(CraftJob)
            .where(CraftJob.character_id == cid, CraftJob.status == "claimed")
            .order_by(CraftJob.updated_at.desc())
            .limit(FEED_LIMIT)
        )
    ).scalars():
        res = j.result or {}
        feed.append(
            {
                "type": "craft",
                "at": j.updated_at,
                "recipe": j.recipe_code,
                "successes": res.get("successes", 0),
                "failures": res.get("failures", 0),
            }
        )
    quests = (
        await db.execute(
            select(CharacterQuest, Quest.name_key)
            .join(Quest, Quest.code == CharacterQuest.quest_code)
            .where(CharacterQuest.character_id == cid, CharacterQuest.claimed_at.is_not(None))
            .order_by(CharacterQuest.claimed_at.desc())
            .limit(FEED_LIMIT)
        )
    ).all()
    ach = (
        await db.execute(
            select(CharacterAchievement, Achievement.name_key, Achievement.status_rarity)
            .join(Achievement, Achievement.code == CharacterAchievement.achievement_code)
            .where(CharacterAchievement.character_id == cid)
            .order_by(CharacterAchievement.unlocked_at.desc())
            .limit(FEED_LIMIT)
        )
    ).all()
    names = await resolve_text_map(db, [k for _, k in quests] + [k for _, k, _ in ach], locale)
    feed += [{"type": "quest", "at": q.claimed_at, "name": names[k]} for q, k in quests]
    feed += [{"type": "achievement", "at": a.unlocked_at, "name": names[k], "rarity": r} for a, k, r in ach]
    for m in (
        await db.execute(
            select(MarketListing)
            .where(
                MarketListing.status == "sold",
                or_(MarketListing.seller_character_id == cid, MarketListing.buyer_character_id == cid),
            )
            .order_by(MarketListing.closed_at.desc())
            .limit(FEED_LIMIT)
        )
    ).scalars():
        feed.append(
            {
                "type": "market_sold" if m.seller_character_id == cid else "market_bought",
                "at": m.closed_at,
                "template_code": m.template_code,
                "total": m.total_price,
            }
        )
    for e in (
        await db.execute(
            select(ProfessionXpEvent)
            .where(
                ProfessionXpEvent.character_id == cid, ProfessionXpEvent.level_after > ProfessionXpEvent.level_before
            )
            .order_by(ProfessionXpEvent.id.desc())
            .limit(FEED_LIMIT)
        )
    ).scalars():
        feed.append(
            {"type": "profession_level", "at": e.created_at, "profession": e.profession_code, "level": e.level_after}
        )
    feed = [f for f in feed if f["at"] is not None]
    feed.sort(key=lambda f: f["at"], reverse=True)
    return [{**f, "at": f["at"].isoformat()} for f in feed[:FEED_LIMIT]]
