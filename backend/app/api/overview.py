from typing import Any

from fastapi import APIRouter

from app.api.deps import Auth, DbSession, LocaleDep
from app.services import characters, overview

router = APIRouter(prefix="/characters/{character_id}", tags=["overview"])


@router.get("/summary")
async def summary(character_id: int, ctx: Auth, db: DbSession, locale: LocaleDep) -> dict[str, Any]:
    ch = await characters.get_owned(db, ctx.user_id, character_id)
    out = await overview.summary(db, ch, locale)
    await db.commit()  # lazily created rows (wallet / progression)
    return out


@router.get("/activity")
async def activity(character_id: int, ctx: Auth, db: DbSession, locale: LocaleDep) -> list[dict[str, Any]]:
    ch = await characters.get_owned(db, ctx.user_id, character_id)
    return await overview.activity(db, ch, locale)
