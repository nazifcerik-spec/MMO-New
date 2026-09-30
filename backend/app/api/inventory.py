from typing import Any, Literal

from fastapi import APIRouter, Query
from pydantic import Field

from app.api.deps import Auth, DbSession, LocaleDep
from app.core import rate_limit
from app.core.config import get_settings
from app.schemas.common import ApiModel
from app.services import characters, inventory

router = APIRouter(tags=["inventory"])


@router.get("/characters/{character_id}/inventory")
async def get_inventory(
    character_id: int,
    ctx: Auth,
    db: DbSession,
    locale: LocaleDep,
    location: Literal["inventory", "mail"] = "inventory",
    after_id: int | None = Query(default=None, ge=1),
    limit: int = Query(default=50, ge=1, le=50),
) -> dict[str, Any]:
    ch = await characters.get_owned(db, ctx.user_id, character_id)
    return await inventory.inventory_view(db, ch, locale, location=location, after_id=after_id, limit=limit)


@router.get("/characters/{character_id}/equipment")
async def get_equipment(character_id: int, ctx: Auth, db: DbSession, locale: LocaleDep) -> dict[str, Any]:
    ch = await characters.get_owned(db, ctx.user_id, character_id)
    return await inventory.equipment_view(db, ch, locale)


class EquipIn(ApiModel):
    instance_id: int = Field(ge=1)
    slot: str | None = Field(default=None, max_length=32, pattern=r"^[a-z0-9_]+$")


@router.post("/characters/{character_id}/equipment/equip")
async def equip(character_id: int, body: EquipIn, ctx: Auth, db: DbSession, locale: LocaleDep) -> dict[str, Any]:
    await rate_limit.hit(f"equip:{ctx.user_id}", get_settings().rl_mutation_user)
    ch = await characters.get_owned(db, ctx.user_id, character_id, for_update=True)
    result = await inventory.equip(db, character=ch, instance_id=body.instance_id, slot=body.slot, actor_id=ctx.user_id)
    await db.commit()
    return {**result, **await inventory.equipment_view(db, ch, locale)}


class UnequipIn(ApiModel):
    slot: str = Field(max_length=32, pattern=r"^[a-z0-9_]+$")


@router.post("/characters/{character_id}/equipment/unequip")
async def unequip(character_id: int, body: UnequipIn, ctx: Auth, db: DbSession, locale: LocaleDep) -> dict[str, Any]:
    await rate_limit.hit(f"equip:{ctx.user_id}", get_settings().rl_mutation_user)
    ch = await characters.get_owned(db, ctx.user_id, character_id, for_update=True)
    result = await inventory.unequip(db, character=ch, slot=body.slot, actor_id=ctx.user_id)
    await db.commit()
    return {**result, **await inventory.equipment_view(db, ch, locale)}


@router.get("/characters/{character_id}/items/{instance_id}/equip-preview")
async def equip_preview(character_id: int, instance_id: int, ctx: Auth, db: DbSession) -> dict[str, Any]:
    ch = await characters.get_owned(db, ctx.user_id, character_id)
    return await inventory.equip_preview(db, ch, instance_id)


@router.post("/characters/{character_id}/mailbox/claim")
async def claim_mail(character_id: int, ctx: Auth, db: DbSession) -> dict[str, int]:
    ch = await characters.get_owned(db, ctx.user_id, character_id, for_update=True)
    out = await inventory.claim_mail(db, ch, actor_id=ctx.user_id)
    await db.commit()
    return out


@router.delete("/characters/{character_id}/items/{instance_id}", status_code=204)
async def destroy(character_id: int, instance_id: int, ctx: Auth, db: DbSession) -> None:
    ch = await characters.get_owned(db, ctx.user_id, character_id, for_update=True)
    await inventory.destroy(db, character=ch, instance_id=instance_id, actor_id=ctx.user_id)
    await db.commit()
