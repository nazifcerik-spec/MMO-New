from typing import Any, Literal

from fastapi import APIRouter, Query
from pydantic import Field

from app.api.deps import Auth, DbSession, IdempotencyKey
from app.core import rate_limit
from app.core.config import get_settings
from app.schemas.common import ApiModel
from app.services import characters, party

router = APIRouter(prefix="/characters/{character_id}/party", tags=["party"])
Role = Literal["tank", "healer", "support", "dps"]


async def _limit(user_id: int) -> None:
    await rate_limit.hit(f"party:{user_id}", get_settings().rl_mutation_user)


@router.get("")
async def view(character_id: int, ctx: Auth, db: DbSession) -> dict[str, Any]:
    ch = await characters.get_owned(db, ctx.user_id, character_id)
    return await party.view(db, ch)


class CreateIn(ApiModel):
    role: Role | None = None


@router.post("", status_code=201)
async def create(character_id: int, body: CreateIn, ctx: Auth, db: DbSession) -> dict[str, Any]:
    await _limit(ctx.user_id)
    ch = await characters.get_owned(db, ctx.user_id, character_id, for_update=True)
    out = await party.create(db, character=ch, role=body.role)
    await db.commit()
    return out


class InviteIn(ApiModel):
    character_name: str = Field(min_length=1, max_length=32)


@router.post("/invites", status_code=201)
async def invite(character_id: int, body: InviteIn, ctx: Auth, db: DbSession) -> dict[str, Any]:
    await _limit(ctx.user_id)
    ch = await characters.get_owned(db, ctx.user_id, character_id)
    out = await party.invite(db, leader=ch, target_name=body.character_name)
    await db.commit()
    return out


@router.post("/invites/{invite_id}/accept")
async def accept(character_id: int, invite_id: int, body: CreateIn, ctx: Auth, db: DbSession) -> dict[str, Any]:
    await _limit(ctx.user_id)
    ch = await characters.get_owned(db, ctx.user_id, character_id, for_update=True)
    out = await party.accept(db, character=ch, invite_id=invite_id, role=body.role)
    await db.commit()
    return out


@router.post("/invites/{invite_id}/decline", status_code=204)
async def decline(character_id: int, invite_id: int, ctx: Auth, db: DbSession) -> None:
    ch = await characters.get_owned(db, ctx.user_id, character_id)
    await party.decline(db, character=ch, invite_id=invite_id)
    await db.commit()


@router.post("/leave", status_code=204)
async def leave(character_id: int, ctx: Auth, db: DbSession) -> None:
    ch = await characters.get_owned(db, ctx.user_id, character_id, for_update=True)
    await party.leave(db, character=ch)
    await db.commit()


class TargetIn(ApiModel):
    character_id: int


@router.post("/kick", status_code=204)
async def kick(character_id: int, body: TargetIn, ctx: Auth, db: DbSession) -> None:
    ch = await characters.get_owned(db, ctx.user_id, character_id)
    await party.kick(db, leader=ch, target_id=body.character_id)
    await db.commit()


@router.post("/leader", status_code=204)
async def leader(character_id: int, body: TargetIn, ctx: Auth, db: DbSession) -> None:
    ch = await characters.get_owned(db, ctx.user_id, character_id)
    await party.set_leader(db, leader=ch, target_id=body.character_id)
    await db.commit()


class RoleIn(ApiModel):
    role: Role


@router.post("/role")
async def role(character_id: int, body: RoleIn, ctx: Auth, db: DbSession) -> dict[str, Any]:
    ch = await characters.get_owned(db, ctx.user_id, character_id)
    out = await party.set_role(db, character=ch, role=body.role)
    await db.commit()
    return out


@router.get("/chat")
async def chat(
    character_id: int, ctx: Auth, db: DbSession, after_id: int | None = Query(default=None, ge=0)
) -> list[dict[str, Any]]:
    ch = await characters.get_owned(db, ctx.user_id, character_id)
    return await party.messages(db, character=ch, after_id=after_id)


class ChatIn(ApiModel):
    body: str = Field(min_length=1, max_length=2000)


@router.post("/chat", status_code=201)
async def send(character_id: int, body: ChatIn, ctx: Auth, db: DbSession, key: IdempotencyKey) -> dict[str, Any]:
    await _limit(ctx.user_id)
    ch = await characters.get_owned(db, ctx.user_id, character_id)
    out = await party.send_message(db, character=ch, body=body.body, key=key)
    await db.commit()
    return out


class GroupAfkIn(ApiModel):
    zone_code: str = Field(max_length=96, pattern=r"^[a-z0-9_]+$")
    duration_s: int = Field(ge=1, le=10800)  # canonical 3 h cap (also enforced by the AFK service)
    risk_level: str | None = Field(default=None, max_length=16)


@router.post("/afk", status_code=201)
async def group_afk(
    character_id: int, body: GroupAfkIn, ctx: Auth, db: DbSession, key: IdempotencyKey
) -> dict[str, Any]:
    await _limit(ctx.user_id)
    ch = await characters.get_owned(db, ctx.user_id, character_id)
    out = await party.group_afk_start(
        db, leader=ch, zone_code=body.zone_code, duration_s=body.duration_s, risk_level=body.risk_level, key=key
    )
    await db.commit()
    return out
