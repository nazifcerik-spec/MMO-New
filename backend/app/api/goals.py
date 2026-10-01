from typing import Any

from fastapi import APIRouter
from pydantic import Field

from app.api.deps import Auth, DbSession, IdempotencyKey, LocaleDep
from app.core import rate_limit
from app.core.config import get_settings
from app.schemas.common import ApiModel
from app.services import characters, goals

router = APIRouter(prefix="/characters/{character_id}", tags=["goals"])
CODE = r"^[a-z][a-z0-9_]{0,95}$"


@router.get("/quests")
async def quest_log(character_id: int, ctx: Auth, db: DbSession, locale: LocaleDep) -> dict[str, Any]:
    ch = await characters.get_owned(db, ctx.user_id, character_id)
    return await goals.quest_log(db, ch, locale)


@router.post("/quests/{code}/accept")
async def accept(character_id: int, code: str, ctx: Auth, db: DbSession) -> dict[str, Any]:
    await rate_limit.hit(f"quest:{ctx.user_id}", get_settings().rl_mutation_user)
    ch = await characters.get_owned(db, ctx.user_id, character_id, for_update=True)
    out = await goals.accept(db, character=ch, code=code)
    await db.commit()
    return out


@router.post("/quests/{code}/abandon", status_code=204)
async def abandon(character_id: int, code: str, ctx: Auth, db: DbSession) -> None:
    ch = await characters.get_owned(db, ctx.user_id, character_id, for_update=True)
    await goals.abandon(db, character=ch, code=code)
    await db.commit()


@router.post("/quests/{code}/claim")
async def claim(character_id: int, code: str, ctx: Auth, db: DbSession, key: IdempotencyKey) -> dict[str, Any]:
    await rate_limit.hit(f"quest:{ctx.user_id}", get_settings().rl_mutation_user)
    ch = await characters.get_owned(db, ctx.user_id, character_id, for_update=True)
    out = await goals.claim(db, character=ch, code=code, key=key)
    await db.commit()
    return out


@router.get("/achievements")
async def achievements(character_id: int, ctx: Auth, db: DbSession, locale: LocaleDep) -> dict[str, Any]:
    ch = await characters.get_owned(db, ctx.user_id, character_id)
    return await goals.achievements_view(db, ch, locale)


@router.get("/titles")
async def titles(character_id: int, ctx: Auth, db: DbSession, locale: LocaleDep) -> dict[str, Any]:
    ch = await characters.get_owned(db, ctx.user_id, character_id)
    return await goals.titles(db, ch, locale)


class TitleIn(ApiModel):
    ref: str = Field(
        min_length=1, max_length=128, pattern=r"^(level:[a-z0-9_]+|class|race|earned:[a-z0-9_]+|guild:[a-z0-9_]+)$"
    )


@router.post("/titles/select")
async def select_title(character_id: int, body: TitleIn, ctx: Auth, db: DbSession) -> dict[str, Any]:
    ch = await characters.get_owned(db, ctx.user_id, character_id)
    out = await goals.select_title(db, character=ch, ref=body.ref)
    await db.commit()
    return out


@router.get("/collections")
async def collections(character_id: int, ctx: Auth, db: DbSession, locale: LocaleDep) -> dict[str, Any]:
    ch = await characters.get_owned(db, ctx.user_id, character_id)
    return await goals.collections(db, ch, locale)
