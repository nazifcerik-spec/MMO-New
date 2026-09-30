from typing import Any

from fastapi import APIRouter
from pydantic import Field

from app.api.deps import Auth, DbSession, IdempotencyKey, LocaleDep
from app.schemas.common import ApiModel
from app.services import characters, talents

router = APIRouter(tags=["talents"])


class PlanIn(ApiModel):
    allocations: dict[str, int] = Field(max_length=64)
    expected_version: int = Field(ge=1)


@router.get("/characters/{character_id}/talents")
async def get_talents(character_id: int, ctx: Auth, db: DbSession, locale: LocaleDep) -> dict[str, Any]:
    ch = await characters.get_owned(db, ctx.user_id, character_id)
    view = await talents.talents_view(db, ch, locale)
    await db.commit()
    return view


@router.post("/characters/{character_id}/talents")
async def allocate_talents(
    character_id: int, body: PlanIn, ctx: Auth, db: DbSession, locale: LocaleDep
) -> dict[str, Any]:
    ch = await characters.get_owned(db, ctx.user_id, character_id, for_update=True)
    await talents.apply_plan(
        db, character=ch, plan=body.allocations, expected_version=body.expected_version, actor_id=ctx.user_id
    )
    await db.commit()
    return await talents.talents_view(db, ch, locale)


@router.post("/characters/{character_id}/talents/reset")
async def reset_talents(character_id: int, ctx: Auth, db: DbSession, key: IdempotencyKey) -> dict[str, Any]:
    ch = await characters.get_owned(db, ctx.user_id, character_id, for_update=True)
    result = await talents.reset(db, character=ch, idempotency_key=key, actor_id=ctx.user_id)
    await db.commit()
    return result


@router.get("/characters/{character_id}/abilities")
async def get_abilities(character_id: int, ctx: Auth, db: DbSession, locale: LocaleDep) -> dict[str, Any]:
    ch = await characters.get_owned(db, ctx.user_id, character_id)
    return await talents.available_abilities(db, ch, locale)
