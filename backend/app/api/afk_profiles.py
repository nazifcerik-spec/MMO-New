from typing import Any

from fastapi import APIRouter
from pydantic import Field

from app.api.deps import Auth, DbSession, LocaleDep
from app.core import rate_limit
from app.core.config import get_settings
from app.schemas.common import ApiModel
from app.services import afk_profiles, characters, tactics

router = APIRouter(tags=["combat-profile"])


class ProfileIn(afk_profiles.ProfileUpdate):
    expected_version: int = Field(ge=1)


class PreviewIn(ApiModel):
    fights: int = Field(default=10, ge=1, le=50)
    potions: int | None = Field(default=None, ge=0, le=50)
    boss: bool = False
    enemies: int | None = Field(default=None, ge=1, le=5)
    # Unsaved Active Tactics draft to simulate (validated exactly like a saved profile).
    tactics: list[dict[str, Any]] | None = Field(default=None, max_length=6)


@router.get("/characters/{character_id}/afk-profile")
async def get_profile(character_id: int, ctx: Auth, db: DbSession, locale: LocaleDep) -> dict[str, Any]:
    ch = await characters.get_owned(db, ctx.user_id, character_id)
    row = await afk_profiles.get_profile(db, ch)
    await db.commit()
    return {"profile": afk_profiles.profile_out(row), "options": await afk_profiles.options(db, ch, locale)}


@router.put("/characters/{character_id}/afk-profile")
async def put_profile(character_id: int, body: ProfileIn, ctx: Auth, db: DbSession) -> dict[str, Any]:
    ch = await characters.get_owned(db, ctx.user_id, character_id)
    update = afk_profiles.ProfileUpdate.model_validate(
        body.model_dump(exclude={"expected_version"}, exclude_unset=True)
    )
    row = await afk_profiles.update_profile(
        db, character=ch, update=update, expected_version=body.expected_version, actor_id=ctx.user_id
    )
    await db.commit()
    return afk_profiles.profile_out(row)


@router.post("/characters/{character_id}/combat/preview")
async def preview(character_id: int, body: PreviewIn, ctx: Auth, db: DbSession, locale: LocaleDep) -> dict[str, Any]:
    await rate_limit.hit(f"preview:{ctx.user_id}", get_settings().rl_mutation_user)
    ch = await characters.get_owned(db, ctx.user_id, character_id)
    draft = await tactics.validate_tactics(db, ch, body.tactics) if body.tactics is not None else None
    result = await afk_profiles.preview(
        db,
        character=ch,
        fights=body.fights,
        potions=body.potions,
        boss=body.boss,
        locale=locale,
        enemies_count=body.enemies,
        tactics_override=draft,
    )
    await db.commit()
    return result
