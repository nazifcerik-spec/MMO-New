from typing import Annotated, Any

from fastapi import APIRouter
from pydantic import Field

from app.api.deps import Auth, DbSession, IdempotencyKey, LocaleDep, require
from app.core import rate_limit
from app.core.config import get_settings
from app.localization.service import resolve_text_map
from app.schemas.common import ApiModel
from app.services import audit, characters, progression
from app.services.auth import AuthContext

router = APIRouter(tags=["progression"])


class AllocateIn(ApiModel):
    points: dict[str, int]
    expected_version: int = Field(ge=1)


class TemplateIn(ApiModel):
    profile_code: str = Field(max_length=32)
    points: int | None = Field(default=None, ge=1, le=3000)
    expected_version: int = Field(ge=1)
    preview: bool = False


class AdminXpIn(ApiModel):
    amount: int = Field(ge=1, le=10**12)
    reason: str = Field(min_length=3, max_length=200)


def _label_keys(view: dict[str, Any]) -> list[str]:
    keys = [f"title.level.{view['title_code']}.name"]
    if view["next_title"]:
        keys.append(f"title.level.{view['next_title']['code']}.name")
    keys += [f"stat.{s.lower()}.name" for s in view["stats"]["primary"]]
    keys += [f"stat.{s}.name" for s in view["stats"]["derived"]]
    return keys


@router.get("/characters/{character_id}/progression")
async def get_progression(character_id: int, ctx: Auth, db: DbSession, locale: LocaleDep) -> dict[str, Any]:
    ch = await characters.get_owned(db, ctx.user_id, character_id)
    view = await progression.progression_view(db, ch)
    view["labels"] = await resolve_text_map(db, _label_keys(view), locale)
    return view


@router.post("/characters/{character_id}/stats/allocate")
async def allocate(
    character_id: int, body: AllocateIn, ctx: Auth, db: DbSession, key: IdempotencyKey
) -> dict[str, Any]:
    await rate_limit.hit(f"mut:{ctx.user_id}", get_settings().rl_mutation_user)
    ch = await characters.get_owned(db, ctx.user_id, character_id, for_update=True)
    alloc = await progression.allocate(
        db, character=ch, points=body.points, expected_version=body.expected_version, idempotency_key=key
    )
    await db.commit()
    return {"allocation": alloc, "unspent_stat_points": ch.unspent_stat_points, "version": ch.version}


@router.get("/content/stat-profiles")
async def list_profiles(db: DbSession, locale: LocaleDep) -> list[dict[str, Any]]:
    profiles = progression.stat_profiles()
    keys = [f"stat_profile.{c}.{f}" for c in profiles for f in ("name", "description")]
    labels = await resolve_text_map(db, keys, locale)
    return [
        {
            "code": c,
            "weights": p["weights"],
            "name": labels[f"stat_profile.{c}.name"],
            "description": labels[f"stat_profile.{c}.description"],
        }
        for c, p in profiles.items()
    ]


@router.post("/characters/{character_id}/stats/auto")
async def auto_allocate(
    character_id: int, body: TemplateIn, ctx: Auth, db: DbSession, key: IdempotencyKey
) -> dict[str, Any]:
    ch = await characters.get_owned(db, ctx.user_id, character_id, for_update=not body.preview)
    points = body.points if body.points is not None else ch.unspent_stat_points
    plan = await progression.template_points(db, ch, body.profile_code, points)
    if body.preview:
        return {"plan": plan, "points": points}
    alloc = await progression.allocate(
        db, character=ch, points=plan, expected_version=body.expected_version, idempotency_key=key, mode="template"
    )
    await db.commit()
    return {"plan": plan, "allocation": alloc, "unspent_stat_points": ch.unspent_stat_points, "version": ch.version}


@router.get("/characters/{character_id}/stats/respec-quote")
async def respec_quote(character_id: int, ctx: Auth, db: DbSession) -> dict[str, Any]:
    ch = await characters.get_owned(db, ctx.user_id, character_id)
    return await progression.respec_quote(db, ch)


@router.post("/characters/{character_id}/stats/respec")
async def do_respec(character_id: int, ctx: Auth, db: DbSession, key: IdempotencyKey) -> dict[str, Any]:
    ch = await characters.get_owned(db, ctx.user_id, character_id, for_update=True)
    result = await progression.respec(db, character=ch, idempotency_key=key)
    await db.commit()
    return result


@router.post("/admin/characters/{character_id}/xp")
async def admin_grant_xp(
    character_id: int,
    body: AdminXpIn,
    db: DbSession,
    key: IdempotencyKey,
    ctx: Annotated[AuthContext, require("economy.grant")],
) -> dict[str, Any]:
    from sqlalchemy import select

    from app.core.errors import NotFoundError
    from app.models.character import Character

    ch = (
        await db.execute(
            select(Character).where(Character.id == character_id, Character.deleted_at.is_(None)).with_for_update()
        )
    ).scalar_one_or_none()
    if ch is None:
        raise NotFoundError("Character not found")
    result = await progression.grant_xp(
        db,
        character=ch,
        amount=body.amount,
        idempotency_key=f"admin:{key}",
        source_type="admin_grant",
        source_id=str(ctx.user_id),
    )
    if not result["replayed"]:
        await audit.record(
            db,
            actor_id=ctx.user_id,
            action="character.xp_grant",
            entity_type="character",
            entity_id=character_id,
            after=result,
            meta={"reason": body.reason},
        )
    await db.commit()
    return result
