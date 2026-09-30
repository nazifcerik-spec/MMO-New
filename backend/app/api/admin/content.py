"""Generic admin content API (drafts, validation, publish bundles, status, history, diff, rollback)."""

from typing import Annotated, Any

from fastapi import APIRouter, Query
from pydantic import Field
from sqlalchemy import select

import app.services.content.types  # noqa: F401  (register content types)
from app.api.deps import Auth, DbSession
from app.core.errors import PermissionDeniedError
from app.game_engine.effects import registry_schema
from app.models.content import ContentRelease
from app.schemas.common import ApiModel
from app.services.auth import AuthContext
from app.services.content import service
from app.services.content.registry import CONTENT_TYPES, ContentType, get_type

router = APIRouter(prefix="/admin/content", tags=["admin:content"])


def _need(ctx: AuthContext, perm: str) -> None:
    if not ctx.has(perm):
        raise PermissionDeniedError("Insufficient permissions", details={"missing": [perm]})


def _read(ctx: AuthContext) -> None:
    _need(ctx, "content.read_drafts")


class CreateIn(ApiModel):
    code: str = Field(max_length=96)
    data: dict[str, Any]


class UpdateIn(ApiModel):
    data: dict[str, Any]
    expected_version: int = Field(ge=0)


class PublishItem(ApiModel):
    entity_type: str
    code: str


class PublishIn(ApiModel):
    items: list[PublishItem] = Field(min_length=1, max_length=200)
    label: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=5000)
    acknowledge_warnings: bool = False


class StatusIn(ApiModel):
    status: str = Field(pattern="^(published|disabled|archived)$")


class RollbackIn(ApiModel):
    revision_no: int = Field(ge=1)
    acknowledge_warnings: bool = False


@router.get("/types")
async def list_types(ctx: Auth) -> list[dict[str, Any]]:
    _read(ctx)
    return [
        {
            "entity_type": ct.entity_type,
            "edit_permission": ct.edit_permission,
            "publish_permission": ct.publish_permission,
            "data_schema": ct.data_schema.model_json_schema(),
        }
        for ct in CONTENT_TYPES.values()
    ]


@router.get("/effects/registry")
async def effect_registry(ctx: Auth) -> list[dict[str, Any]]:
    _read(ctx)
    return registry_schema()


@router.post("/releases")
async def publish(body: PublishIn, ctx: Auth, db: DbSession) -> dict[str, Any]:
    items: list[tuple[ContentType, str]] = []
    for it in body.items:
        ct = get_type(it.entity_type)
        _need(ctx, ct.publish_permission)
        items.append((ct, it.code))
    release = await service.publish(
        db,
        items,
        actor_id=ctx.user_id,
        label=body.label,
        notes=body.notes,
        acknowledge_warnings=body.acknowledge_warnings,
    )
    await db.commit()
    return {"release_version": release.version_no, "published": [i.model_dump() for i in body.items]}


@router.get("/releases")
async def list_releases(
    ctx: Auth, db: DbSession, limit: Annotated[int, Query(ge=1, le=100)] = 25
) -> list[dict[str, Any]]:
    _read(ctx)
    rows = (await db.execute(select(ContentRelease).order_by(ContentRelease.version_no.desc()).limit(limit))).scalars()
    return [
        {
            "version_no": r.version_no,
            "label": r.label,
            "notes": r.notes,
            "created_by": r.created_by,
            "created_at": r.created_at,
        }
        for r in rows
    ]


@router.get("/{entity_type}")
async def list_entities(
    entity_type: str,
    ctx: Auth,
    db: DbSession,
    status: str | None = None,
    search: Annotated[str | None, Query(max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    _read(ctx)
    ct = get_type(entity_type)
    rows, total = await service.list_admin(db, ct, status=status, search=search, limit=limit, offset=offset)
    return {
        "items": [
            {
                "code": r.code,
                "status": r.status,
                "revision_no": r.revision_no,
                "version": r.version,
                "published_at": r.published_at,
                "updated_at": r.updated_at,
            }
            for r in rows
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.post("/{entity_type}", status_code=201)
async def create_entity(entity_type: str, body: CreateIn, ctx: Auth, db: DbSession) -> dict[str, Any]:
    ct = get_type(entity_type)
    _need(ctx, ct.edit_permission)
    row = await service.create(db, ct, code=body.code, data=body.data, actor_id=ctx.user_id)
    view = await service.working_view(db, ct, row)
    await db.commit()
    return view


@router.get("/{entity_type}/{code}")
async def get_entity(entity_type: str, code: str, ctx: Auth, db: DbSession) -> dict[str, Any]:
    _read(ctx)
    ct = get_type(entity_type)
    row = await service.get_row(db, ct, code)
    view = await service.working_view(db, ct, row)
    view["issues"] = [i.as_dict() for i in await service.validate(db, ct, code, view["data"])]
    return view


@router.put("/{entity_type}/{code}")
async def update_entity(entity_type: str, code: str, body: UpdateIn, ctx: Auth, db: DbSession) -> dict[str, Any]:
    ct = get_type(entity_type)
    _need(ctx, ct.edit_permission)
    view = await service.update(
        db, ct, code=code, data=body.data, expected_version=body.expected_version, actor_id=ctx.user_id
    )
    await db.commit()
    return view


@router.delete("/{entity_type}/{code}/draft", status_code=204)
async def discard(entity_type: str, code: str, ctx: Auth, db: DbSession) -> None:
    ct = get_type(entity_type)
    _need(ctx, ct.edit_permission)
    await service.discard_draft(db, ct, code=code, actor_id=ctx.user_id)
    await db.commit()


@router.delete("/{entity_type}/{code}", status_code=204)
async def delete_unpublished(entity_type: str, code: str, ctx: Auth, db: DbSession) -> None:
    ct = get_type(entity_type)
    _need(ctx, ct.edit_permission)
    await service.delete_unpublished(db, ct, code=code, actor_id=ctx.user_id)
    await db.commit()


@router.post("/{entity_type}/{code}/validate")
async def validate_entity(entity_type: str, code: str, ctx: Auth, db: DbSession) -> dict[str, Any]:
    _read(ctx)
    ct = get_type(entity_type)
    row = await service.get_row(db, ct, code)
    view = await service.working_view(db, ct, row)
    issues = await service.validate(db, ct, code, view["data"])
    return {"ok": not any(i.level == "error" for i in issues), "issues": [i.as_dict() for i in issues]}


@router.post("/{entity_type}/{code}/status")
async def change_status(entity_type: str, code: str, body: StatusIn, ctx: Auth, db: DbSession) -> dict[str, Any]:
    ct = get_type(entity_type)
    _need(ctx, ct.publish_permission)
    row = await service.set_status(db, ct, code=code, status=body.status, actor_id=ctx.user_id)
    await db.commit()
    return {"code": row.code, "status": row.status, "revision_no": row.revision_no}


@router.get("/{entity_type}/{code}/history")
async def get_history(entity_type: str, code: str, ctx: Auth, db: DbSession) -> list[dict[str, Any]]:
    _read(ctx)
    return await service.history(db, get_type(entity_type), code)


@router.get("/{entity_type}/{code}/revisions/{revision_no}")
async def get_revision(entity_type: str, code: str, revision_no: int, ctx: Auth, db: DbSession) -> dict[str, Any]:
    _read(ctx)
    rev = await service.get_revision(db, get_type(entity_type), code, revision_no)
    return {
        "revision_no": rev.revision_no,
        "status": rev.status,
        "data": rev.data,
        "data_hash": rev.data_hash,
        "created_at": rev.created_at,
    }


@router.get("/{entity_type}/{code}/diff")
async def diff(
    entity_type: str,
    code: str,
    ctx: Auth,
    db: DbSession,
    from_rev: int = Query(ge=1),
    to_rev: int | None = Query(default=None, ge=1),
) -> list[dict[str, Any]]:
    _read(ctx)
    return await service.diff_revisions(db, get_type(entity_type), code, from_rev, to_rev)


@router.post("/{entity_type}/{code}/rollback")
async def rollback(entity_type: str, code: str, body: RollbackIn, ctx: Auth, db: DbSession) -> dict[str, Any]:
    ct = get_type(entity_type)
    _need(ctx, ct.publish_permission)
    release = await service.rollback(
        db,
        ct,
        code=code,
        revision_no=body.revision_no,
        actor_id=ctx.user_id,
        acknowledge_warnings=body.acknowledge_warnings,
    )
    await db.commit()
    return {"release_version": release.version_no}
