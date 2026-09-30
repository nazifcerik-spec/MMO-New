from typing import Any

from fastapi import APIRouter, Query
from pydantic import Field

from app.api.deps import Auth, DbSession, LocaleDep, OptionalAuth
from app.core import rate_limit
from app.core.config import get_settings
from app.core.errors import UnauthorizedError
from app.models.character import Character
from app.schemas.common import ApiModel
from app.services import afk_profiles, characters, world

router = APIRouter(tags=["world"])


async def _character(db: DbSession, ctx: Any, character_id: int | None) -> Character | None:
    if character_id is None:
        return None
    if ctx is None:
        raise UnauthorizedError("Login required")
    return await characters.get_owned(db, ctx.user_id, character_id)


@router.get("/zones")
async def list_zones(
    db: DbSession,
    locale: LocaleDep,
    ctx: OptionalAuth,
    character_id: int | None = None,
    after: int | None = Query(default=None, ge=0),
    limit: int = Query(default=20, ge=1, le=world.MAX_PAGE),
) -> dict[str, Any]:
    ch = await _character(db, ctx, character_id)
    return await world.list_zones(db, locale, character=ch, after=after, limit=limit)


@router.get("/zones/{code}")
async def zone_detail(
    code: str, db: DbSession, locale: LocaleDep, ctx: OptionalAuth, character_id: int | None = None
) -> dict[str, Any]:
    ch = await _character(db, ctx, character_id)
    return await world.zone_detail(db, code, locale, ch)


class ZonePreviewIn(ApiModel):
    fights: int = Field(default=10, ge=1, le=30)
    potions: int | None = Field(default=None, ge=0, le=50)
    boss: bool = False


@router.post("/characters/{character_id}/zones/{code}/preview")
async def zone_preview(
    character_id: int, code: str, body: ZonePreviewIn, ctx: Auth, db: DbSession, locale: LocaleDep
) -> dict[str, Any]:
    """Simulate the character's current AFK profile against this zone's real encounter pool (no rewards)."""
    await rate_limit.hit(f"preview:{ctx.user_id}", get_settings().rl_mutation_user)
    ch = await characters.get_owned(db, ctx.user_id, character_id)
    bundle = await world.load_bundle(db, code)
    result = await afk_profiles.preview(
        db, character=ch, fights=body.fights, potions=body.potions, boss=body.boss, locale=locale, zone=bundle
    )
    await db.commit()
    return result
