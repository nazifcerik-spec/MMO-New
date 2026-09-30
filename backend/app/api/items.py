from typing import Annotated, Any

from fastapi import APIRouter, Query
from pydantic import Field

from app.api.deps import Auth, DbSession, IdempotencyKey, LocaleDep, require
from app.schemas.common import ApiModel
from app.services import characters, items
from app.services.auth import AuthContext

router = APIRouter(tags=["items"])


@router.get("/items/templates")
async def catalog(
    db: DbSession,
    locale: LocaleDep,
    category: str | None = Query(default=None, max_length=32),
    tier: int | None = Query(default=None, ge=0, le=10),
    rarity: str | None = Query(default=None, max_length=16),
    after_id: int | None = Query(default=None, ge=1),
    limit: int = Query(default=20, ge=1, le=items.MAX_PAGE),
) -> dict[str, Any]:
    return await items.catalog(db, locale, category=category, tier=tier, rarity=rarity, after_id=after_id, limit=limit)


@router.get("/items/templates/{code}")
async def template(code: str, db: DbSession, locale: LocaleDep) -> dict[str, Any]:
    return await items.template_detail(db, code, locale)


@router.get("/characters/{character_id}/items")
async def list_items(
    character_id: int,
    ctx: Auth,
    db: DbSession,
    locale: LocaleDep,
    location: str | None = Query(default=None, pattern=r"^(inventory|equipped|bank|mail|market)$"),
    after_id: int | None = Query(default=None, ge=1),
    limit: int = Query(default=20, ge=1, le=items.MAX_PAGE),
) -> dict[str, Any]:
    ch = await characters.get_owned(db, ctx.user_id, character_id)
    rows = await items.list_instances(db, ch.id, location=location, after_id=after_id, limit=limit)
    return {
        "items": [await items.instance_view(db, r, locale) for r in rows],
        "next_after_id": rows[-1].id if len(rows) == limit else None,
    }


@router.get("/characters/{character_id}/items/{instance_id}")
async def item_detail(
    character_id: int, instance_id: int, ctx: Auth, db: DbSession, locale: LocaleDep
) -> dict[str, Any]:
    ch = await characters.get_owned(db, ctx.user_id, character_id)
    inst = await items.get_owned_instance(db, ch.id, instance_id)
    return await items.instance_view(db, inst, locale, ch)


class GrantIn(ApiModel):
    template_code: str = Field(max_length=96, pattern=r"^[a-z0-9_]+$")
    quantity: int = Field(default=1, ge=1, le=9999)
    seed: int | None = Field(default=None, ge=0, le=2**62)
    reason: str = Field(max_length=200)


@router.post("/admin/characters/{character_id}/items", status_code=201)
async def grant(
    character_id: int,
    body: GrantIn,
    db: DbSession,
    key: IdempotencyKey,
    locale: LocaleDep,
    ctx: Annotated[AuthContext, require("economy.grant")],
) -> dict[str, Any]:
    ch = await characters.get_any(db, character_id, for_update=True)
    inst = await items.create_instance(
        db,
        character=ch,
        template_code=body.template_code,
        source_type="admin",
        source_id=f"user:{ctx.user_id}",
        idempotency_key=key,
        quantity=body.quantity,
        seed=body.seed,
        actor_id=ctx.user_id,
    )
    await items.audit_grant(db, inst, ctx.user_id, body.reason)
    await db.commit()
    return await items.instance_view(db, inst, locale, ch)


class RollPreviewIn(ApiModel):
    seeds: list[int] = Field(min_length=1, max_length=20)


@router.post("/admin/items/{code}/roll-preview")
async def roll_preview(
    code: str, body: RollPreviewIn, db: DbSession, _: Annotated[AuthContext, require("item.edit")]
) -> dict[str, Any]:
    return {"rolls": await items.roll_preview(db, code, body.seeds)}
