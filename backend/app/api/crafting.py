from typing import Any

from fastapi import APIRouter, Query
from pydantic import Field

from app.api.deps import Auth, DbSession, IdempotencyKey, LocaleDep
from app.core import rate_limit
from app.core.config import get_settings
from app.schemas.common import ApiModel
from app.services import characters, crafting

router = APIRouter(tags=["crafting"])
CODE = r"^[a-z0-9_]+$"


async def _limit(user_id: int) -> None:
    await rate_limit.hit(f"craft:{user_id}", get_settings().rl_mutation_user)


@router.get("/characters/{character_id}/recipes")
async def recipes(
    character_id: int,
    ctx: Auth,
    db: DbSession,
    locale: LocaleDep,
    profession: str | None = Query(default=None, max_length=64, pattern=CODE),
) -> list[dict[str, Any]]:
    ch = await characters.get_owned(db, ctx.user_id, character_id)
    out = await crafting.recipes_view(db, ch, locale, profession)
    await db.commit()
    return out


class LearnIn(ApiModel):
    instance_id: int


@router.post("/characters/{character_id}/recipes/learn")
async def learn(character_id: int, body: LearnIn, ctx: Auth, db: DbSession) -> dict[str, Any]:
    await _limit(ctx.user_id)
    ch = await characters.get_owned(db, ctx.user_id, character_id, for_update=True)
    out = await crafting.learn_from_scroll(db, character=ch, instance_id=body.instance_id, actor_id=ctx.user_id)
    await db.commit()
    return out


@router.get("/characters/{character_id}/crafts")
async def jobs(character_id: int, ctx: Auth, db: DbSession) -> list[dict[str, Any]]:
    ch = await characters.get_owned(db, ctx.user_id, character_id)
    return await crafting.jobs_view(db, ch)


class CraftIn(ApiModel):
    recipe_code: str = Field(max_length=96, pattern=CODE)
    quantity: int = Field(ge=1, le=1000)


@router.post("/characters/{character_id}/crafts")
async def start(character_id: int, body: CraftIn, ctx: Auth, db: DbSession, key: IdempotencyKey) -> dict[str, Any]:
    await _limit(ctx.user_id)
    ch = await characters.get_owned(db, ctx.user_id, character_id, for_update=True)
    job = await crafting.start_craft(db, character=ch, recipe_code=body.recipe_code, quantity=body.quantity, key=key)
    await db.commit()
    return {"id": job.id, "ends_at": job.ends_at.isoformat(), "quantity": job.quantity, "recipe": job.recipe_code}


@router.post("/characters/{character_id}/crafts/{job_id}/cancel")
async def cancel(character_id: int, job_id: int, ctx: Auth, db: DbSession) -> dict[str, Any]:
    await _limit(ctx.user_id)
    ch = await characters.get_owned(db, ctx.user_id, character_id, for_update=True)
    out = await crafting.cancel_craft(db, character=ch, job_id=job_id)
    await db.commit()
    return out


@router.post("/characters/{character_id}/crafts/{job_id}/claim")
async def claim(character_id: int, job_id: int, ctx: Auth, db: DbSession, key: IdempotencyKey) -> dict[str, Any]:
    await _limit(ctx.user_id)
    ch = await characters.get_owned(db, ctx.user_id, character_id, for_update=True)
    out = await crafting.claim_craft(db, character=ch, job_id=job_id, key=key)
    await db.commit()
    return out


@router.get("/content/imbues")
async def imbues(db: DbSession, locale: LocaleDep) -> list[dict[str, Any]]:
    return await crafting.imbues_view(db, locale)


class RerollIn(ApiModel):
    affix_index: int = Field(ge=0, le=20)


@router.post("/characters/{character_id}/items/{instance_id}/reroll")
async def reroll(
    character_id: int, instance_id: int, body: RerollIn, ctx: Auth, db: DbSession, key: IdempotencyKey
) -> dict[str, Any]:
    await _limit(ctx.user_id)
    ch = await characters.get_owned(db, ctx.user_id, character_id, for_update=True)
    out = await crafting.reroll_affix(db, character=ch, instance_id=instance_id, affix_index=body.affix_index, key=key)
    await db.commit()
    return out


class ImbueIn(ApiModel):
    imbue_code: str = Field(max_length=96, pattern=CODE)


@router.post("/characters/{character_id}/items/{instance_id}/imbue")
async def imbue(
    character_id: int, instance_id: int, body: ImbueIn, ctx: Auth, db: DbSession, key: IdempotencyKey
) -> dict[str, Any]:
    await _limit(ctx.user_id)
    ch = await characters.get_owned(db, ctx.user_id, character_id, for_update=True)
    out = await crafting.imbue(db, character=ch, instance_id=instance_id, imbue_code=body.imbue_code, key=key)
    await db.commit()
    return out


@router.post("/characters/{character_id}/items/{instance_id}/salvage")
async def salvage(character_id: int, instance_id: int, ctx: Auth, db: DbSession, key: IdempotencyKey) -> dict[str, Any]:
    await _limit(ctx.user_id)
    ch = await characters.get_owned(db, ctx.user_id, character_id, for_update=True)
    out = await crafting.salvage(db, character=ch, instance_id=instance_id, key=key)
    await db.commit()
    return out
