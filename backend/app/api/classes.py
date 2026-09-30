from typing import Any

from fastapi import APIRouter
from pydantic import Field

from app.api.deps import Auth, DbSession, IdempotencyKey, LocaleDep
from app.schemas.common import ApiModel
from app.services import characters, classes

router = APIRouter(tags=["classes"])


class PromoteIn(ApiModel):
    branch_code: str = Field(max_length=96)


class SpecializeIn(ApiModel):
    specialization_code: str = Field(max_length=96)


class PathChangeIn(ApiModel):
    branch_code: str | None = Field(default=None, max_length=96)
    specialization_code: str | None = Field(default=None, max_length=96)


@router.get("/content/classes")
async def list_classes(db: DbSession, locale: LocaleDep) -> list[dict[str, Any]]:
    return await classes.class_cards(db, locale)


@router.get("/characters/{character_id}/class")
async def get_class(character_id: int, ctx: Auth, db: DbSession, locale: LocaleDep) -> dict[str, Any]:
    ch = await characters.get_owned(db, ctx.user_id, character_id)
    view = await classes.class_view(db, ch, locale)
    await db.commit()  # lazily created progression rows / unlocked milestones
    return view


@router.post("/characters/{character_id}/class/promote")
async def promote(character_id: int, body: PromoteIn, ctx: Auth, db: DbSession, locale: LocaleDep) -> dict[str, Any]:
    ch = await characters.get_owned(db, ctx.user_id, character_id, for_update=True)
    await classes.promote(db, character=ch, branch_code=body.branch_code, actor_id=ctx.user_id)
    await db.commit()
    return await classes.class_view(db, ch, locale)


@router.post("/characters/{character_id}/class/specialize")
async def specialize(
    character_id: int, body: SpecializeIn, ctx: Auth, db: DbSession, locale: LocaleDep
) -> dict[str, Any]:
    ch = await characters.get_owned(db, ctx.user_id, character_id, for_update=True)
    await classes.specialize(db, character=ch, spec_code=body.specialization_code, actor_id=ctx.user_id)
    await db.commit()
    return await classes.class_view(db, ch, locale)


@router.post("/characters/{character_id}/class/change-path")
async def change_path(
    character_id: int, body: PathChangeIn, ctx: Auth, db: DbSession, key: IdempotencyKey, locale: LocaleDep
) -> dict[str, Any]:
    ch = await characters.get_owned(db, ctx.user_id, character_id, for_update=True)
    await classes.change_path(
        db,
        character=ch,
        branch_code=body.branch_code,
        spec_code=body.specialization_code,
        idempotency_key=key,
        actor_id=ctx.user_id,
    )
    await db.commit()
    return await classes.class_view(db, ch, locale)
