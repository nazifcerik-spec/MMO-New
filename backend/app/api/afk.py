from typing import Annotated, Any

from fastapi import APIRouter, Query
from pydantic import Field

from app.api.deps import Auth, DbSession, IdempotencyKey, LocaleDep, require
from app.core import rate_limit
from app.core.config import get_settings
from app.localization.service import resolve_text_map
from app.schemas.common import ApiModel
from app.services import afk, characters
from app.services.auth import AuthContext

router = APIRouter(tags=["afk"])


class StartIn(ApiModel):
    zone_code: str = Field(max_length=96, pattern=r"^[a-z0-9_]+$")
    duration_s: int = Field(ge=60, le=10_800)  # canonical 3 h hard cap (config may be stricter)
    risk_level: str | None = Field(default=None, max_length=16)
    profession_task: dict[str, Any] | None = None


async def _view(db: DbSession, session: Any, locale: str) -> dict[str, Any]:
    names = await resolve_text_map(db, [f"zone.{session.zone_code}.name"], locale)
    return afk.session_view(session, afk.now_utc(), {session.zone_code: names[f"zone.{session.zone_code}.name"]})


@router.post("/characters/{character_id}/afk/start", status_code=201)
async def start(
    character_id: int, body: StartIn, ctx: Auth, db: DbSession, key: IdempotencyKey, locale: LocaleDep
) -> dict[str, Any]:
    await rate_limit.hit(f"afk:{ctx.user_id}", get_settings().rl_mutation_user)
    ch = await characters.get_owned(db, ctx.user_id, character_id, for_update=True)
    session = await afk.start(
        db,
        character=ch,
        zone_code=body.zone_code,
        duration_s=body.duration_s,
        risk_level=body.risk_level,
        idempotency_key=key,
        profession_task=body.profession_task,
    )
    await db.commit()
    return await _view(db, session, locale)


@router.get("/characters/{character_id}/afk")
async def current(character_id: int, ctx: Auth, db: DbSession, locale: LocaleDep) -> dict[str, Any]:
    ch = await characters.get_owned(db, ctx.user_id, character_id)
    session = await afk.active_session(db, ch.id)
    return {"session": await _view(db, session, locale) if session else None, "server_now": afk.now_utc().isoformat()}


@router.post("/characters/{character_id}/afk/stop")
async def stop(character_id: int, ctx: Auth, db: DbSession, locale: LocaleDep) -> dict[str, Any]:
    ch = await characters.get_owned(db, ctx.user_id, character_id)
    session = await afk.stop(db, character=ch)
    await db.commit()
    return await _view(db, session, locale)


@router.post("/characters/{character_id}/afk/claim")
async def claim(character_id: int, ctx: Auth, db: DbSession, key: IdempotencyKey) -> dict[str, Any]:
    await rate_limit.hit(f"afk:{ctx.user_id}", get_settings().rl_mutation_user)
    ch = await characters.get_owned(db, ctx.user_id, character_id, for_update=True)
    out = await afk.claim(db, character=ch, idempotency_key=key)
    await db.commit()
    return out


@router.get("/characters/{character_id}/afk/history")
async def history(
    character_id: int,
    ctx: Auth,
    db: DbSession,
    before_id: int | None = Query(default=None, ge=1),
    limit: int = Query(default=10, ge=1, le=afk.MAX_HISTORY),
) -> dict[str, Any]:
    ch = await characters.get_owned(db, ctx.user_id, character_id)
    rows = await afk.history(db, ch.id, before_id=before_id, limit=limit)
    return {
        "items": [
            (r.claim_result or {}) | {"claimed_at": r.claimed_at.isoformat() if r.claimed_at else None} for r in rows
        ],
        "next_before_id": rows[-1].id if len(rows) == limit else None,
    }


@router.post("/admin/afk/sweep")
async def sweep(db: DbSession, _: Annotated[AuthContext, require("system.manage")]) -> dict[str, int]:
    n = await afk.sweep(db)
    await db.commit()
    return {"resolved": n}


@router.post("/admin/afk/{session_id}/replay")
async def replay(
    session_id: int, db: DbSession, _: Annotated[AuthContext, require("balance.simulate")]
) -> dict[str, Any]:
    return await afk.replay(db, session_id)
