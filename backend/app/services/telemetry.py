"""Privacy-conscious aggregate telemetry (Phase 25). Computed on demand from authoritative game tables —
no extra tracking events, no identifiers in the output, and small buckets are suppressed (k-anonymity)."""

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Integer, cast, func, literal_column, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.afk import AfkSession
from app.models.auth import User
from app.models.character import Character
from app.models.crafting import CraftJob, Recipe

MIN_BUCKET = 3  # buckets with fewer than this many events are folded into "other"
MAX_DAYS = 90


def _suppress(counts: dict[str, int]) -> dict[str, int]:
    out: dict[str, int] = {}
    other = 0
    for k, v in sorted(counts.items(), key=lambda kv: -kv[1]):
        if v >= MIN_BUCKET:
            out[k] = v
        else:
            other += v
    if other:
        out["other"] = other
    return out


async def _count(db: AsyncSession, stmt: Any) -> int:
    return int((await db.execute(stmt)).scalar_one())


async def summary(db: AsyncSession, *, days: int) -> dict[str, Any]:
    days = max(1, min(days, MAX_DAYS))
    start = datetime.now(UTC) - timedelta(days=days)
    in_window = AfkSession.created_at >= start
    started = (await db.execute(select(func.count()).select_from(AfkSession).where(in_window))).scalar_one()
    claimed = (
        await db.execute(select(func.count()).select_from(AfkSession).where(in_window, AfkSession.status == "claimed"))
    ).scalar_one()
    stopped = (
        await db.execute(
            select(func.count()).select_from(AfkSession).where(in_window, AfkSession.stopped_at.is_not(None))
        )
    ).scalar_one()
    res = AfkSession.claim_result["result"]
    fights, deaths = (
        await db.execute(
            select(
                func.coalesce(func.sum(cast(res["fights"].astext, Integer)), 0),
                func.coalesce(func.sum(cast(res["deaths"].astext, Integer)), 0),
            ).where(in_window, AfkSession.status == "claimed")
        )
    ).one()
    zones: dict[str, int] = dict(
        (
            await db.execute(select(AfkSession.zone_code, func.count()).where(in_window).group_by(AfkSession.zone_code))
        ).all()
    )
    prof: Any = literal_column("afk_sessions.snapshot -> 'profession_task' ->> 'profession_code'")
    gather: dict[str, int] = dict(
        (
            await db.execute(
                select(prof, func.count()).select_from(AfkSession).where(in_window, prof.is_not(None)).group_by(prof)
            )
        ).all()
    )
    crafts: dict[str, int] = dict(
        (
            await db.execute(
                select(Recipe.profession_code, func.count())
                .select_from(CraftJob)
                .join(Recipe, Recipe.code == CraftJob.recipe_code)
                .where(CraftJob.created_at >= start)
                .group_by(Recipe.profession_code)
            )
        ).all()
    )
    users = select(User.id).where(User.created_at >= start).scalar_subquery()
    chars = select(Character.id).where(Character.user_id.in_(users), Character.deleted_at.is_(None))
    distinct_chars = select(func.count(func.distinct(Character.user_id)))
    distinct_afk = select(func.count(func.distinct(AfkSession.user_id))).where(AfkSession.user_id.in_(users))
    funnel = {
        "registered": await _count(db, select(func.count()).select_from(User).where(User.created_at >= start)),
        "created_character": await _count(db, distinct_chars.where(Character.user_id.in_(users))),
        "started_afk": await _count(db, distinct_afk),
        "claimed_afk": await _count(db, distinct_afk.where(AfkSession.status == "claimed")),
        "reached_level_10": await _count(db, distinct_chars.where(Character.id.in_(chars), Character.level >= 10)),
        "reached_level_100": await _count(db, distinct_chars.where(Character.id.in_(chars), Character.level >= 100)),
    }
    steps = list(funnel.items())
    return {
        "window_days": days,
        "min_bucket": MIN_BUCKET,
        "sessions": {
            "started": started,
            "claimed": claimed,
            "stopped_early": stopped,
            "completion_rate": round(claimed / started, 4) if started else 0.0,
            "abandonment_rate": round(stopped / started, 4) if started else 0.0,
            "death_rate_per_fight": round(int(deaths) / int(fights), 4) if fights else 0.0,
        },
        "zones": _suppress({k: int(v) for k, v in zones.items()}),
        "profession_usage": {
            "gathering": _suppress({k: int(v) for k, v in gather.items() if k}),
            "crafting": _suppress({k: int(v) for k, v in crafts.items()}),
        },
        "funnel": [
            {
                "step": k,
                "count": int(v),
                "drop_off_pct": round(100 * (1 - v / steps[i - 1][1]), 1) if i and steps[i - 1][1] else 0.0,
            }
            for i, (k, v) in enumerate(steps)
        ],
    }
