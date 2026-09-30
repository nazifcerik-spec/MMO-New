from typing import Any

from fastapi import APIRouter, Query, Response

from app.api.deps import Auth, DbSession, LocaleDep
from app.content.names import validate_name
from app.core import rate_limit
from app.core.config import get_settings
from app.core.errors import AppError
from app.schemas.auth import CharacterCreateIn, CharacterOut, NameCheckOut
from app.services import character_options, characters

router = APIRouter(tags=["characters"])


@router.get("/content/character-options")
async def get_character_options(db: DbSession, locale: LocaleDep) -> dict[str, list[dict[str, Any]]]:
    return await character_options.get_character_options(db, locale)


@router.get("/characters", response_model=list[CharacterOut])
async def list_my_characters(ctx: Auth, db: DbSession) -> list[Any]:
    return await characters.list_characters(db, ctx.user_id)


@router.get("/characters/name-check", response_model=NameCheckOut)
async def name_check(ctx: Auth, db: DbSession, name: str = Query(max_length=64)) -> NameCheckOut:
    await rate_limit.hit(f"namecheck:{ctx.user_id}", get_settings().rl_mutation_user)
    try:
        display = validate_name(name)
    except AppError as exc:
        return NameCheckOut(name=name, available=False, valid=False, error_code=exc.code)
    return NameCheckOut(name=display, valid=True, available=await characters.is_name_available(db, display))


@router.post("/characters", response_model=CharacterOut, status_code=201)
async def create_character(body: CharacterCreateIn, ctx: Auth, db: DbSession) -> Any:
    await rate_limit.hit(f"mut:{ctx.user_id}", get_settings().rl_mutation_user)
    ch = await characters.create_character(
        db, user_id=ctx.user_id, name=body.name, race_id=body.race_id, base_class_id=body.base_class_id
    )
    await db.commit()
    return ch


@router.get("/characters/{character_id}", response_model=CharacterOut)
async def get_character(character_id: int, ctx: Auth, db: DbSession) -> Any:
    return await characters.get_owned(db, ctx.user_id, character_id)


@router.delete("/characters/{character_id}", status_code=204)
async def delete_character(character_id: int, ctx: Auth, db: DbSession) -> Response:
    await characters.soft_delete_character(db, user_id=ctx.user_id, character_id=character_id)
    await db.commit()
    return Response(status_code=204)
