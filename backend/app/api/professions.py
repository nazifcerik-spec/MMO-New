from typing import Annotated, Any

from fastapi import APIRouter, Query
from pydantic import Field

from app.api.deps import Auth, DbSession, IdempotencyKey, LocaleDep, require
from app.core import rate_limit
from app.core.config import get_settings
from app.schemas.common import ApiModel
from app.services import characters, professions
from app.services.auth import AuthContext

router = APIRouter(tags=["professions"])


@router.get("/content/professions")
async def catalog(db: DbSession, locale: LocaleDep) -> list[dict[str, Any]]:
    return await professions.catalog_view(db, locale)


@router.get("/characters/{character_id}/professions")
async def my_professions(character_id: int, ctx: Auth, db: DbSession, locale: LocaleDep) -> dict[str, Any]:
    ch = await characters.get_owned(db, ctx.user_id, character_id)
    out = await professions.character_view(db, ch, locale)
    await db.commit()  # lazily created progress rows
    return out


class LicenseIn(ApiModel):
    active: bool


@router.post("/characters/{character_id}/professions/{code}/license")
async def license(
    character_id: int, code: str, body: LicenseIn, ctx: Auth, db: DbSession, key: IdempotencyKey
) -> dict[str, Any]:
    await rate_limit.hit(f"prof:{ctx.user_id}", get_settings().rl_mutation_user)
    ch = await characters.get_owned(db, ctx.user_id, character_id, for_update=True)
    out = await professions.set_license(db, character=ch, code=code, active=body.active, idempotency_key=key)
    await db.commit()
    return out


class SpecializeIn(ApiModel):
    specialization_code: str = Field(max_length=96, pattern=r"^[a-z0-9_]+$")


@router.post("/characters/{character_id}/professions/{code}/specialize")
async def specialize(
    character_id: int, code: str, body: SpecializeIn, ctx: Auth, db: DbSession, key: IdempotencyKey
) -> dict[str, Any]:
    ch = await characters.get_owned(db, ctx.user_id, character_id, for_update=True)
    out = await professions.specialize(
        db, character=ch, code=code, specialization_code=body.specialization_code, idempotency_key=key
    )
    await db.commit()
    return out


@router.get("/characters/{character_id}/professions/{code}/node-check")
async def node_check(
    character_id: int, code: str, ctx: Auth, db: DbSession, tier: int = Query(ge=0, le=10)
) -> dict[str, Any]:
    ch = await characters.get_owned(db, ctx.user_id, character_id)
    return await professions.node_check(db, ch, code, tier)


class AdminXpIn(ApiModel):
    amount: int = Field(ge=1, le=10**9)
    reason: str = Field(max_length=200)


@router.post("/admin/characters/{character_id}/professions/{code}/xp")
async def admin_xp(
    character_id: int,
    code: str,
    body: AdminXpIn,
    db: DbSession,
    key: IdempotencyKey,
    ctx: Annotated[AuthContext, require("economy.grant")],
) -> dict[str, Any]:
    from app.services import audit

    ch = await characters.get_any(db, character_id, for_update=True)
    out = await professions.grant_xp(
        db, character=ch, profession_code=code, amount=body.amount, idempotency_key=f"admin:{key}",
        source_type="admin", apply_bonus=False,
    )  # fmt: skip
    await audit.record(
        db, actor_id=ctx.user_id, action="profession.xp_grant", entity_type="character", entity_id=ch.id,
        meta={"profession": code, "amount": body.amount, "reason": body.reason},
    )  # fmt: skip
    await db.commit()
    return out
