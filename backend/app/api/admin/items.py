"""Admin Item Studio API (separate from public item endpoints; server-side filtering; RBAC per action)."""

import json
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from pydantic import Field

from app.api.deps import DbSession, require
from app.core.errors import ValidationFailedError
from app.game_engine.item_generator import GeneratorParams
from app.schemas.common import ApiModel
from app.services import item_studio
from app.services.auth import AuthContext

router = APIRouter(prefix="/admin/items", tags=["admin-items"])
Reader = Annotated[AuthContext, require("content.read_drafts")]
Editor = Annotated[AuthContext, require("item.edit")]
Translator = Annotated[AuthContext, require("localization.edit")]


@router.get("")
async def list_items(db: DbSession, _: Reader, f: Annotated[item_studio.ListFilters, Depends()]) -> dict[str, Any]:
    return await item_studio.list_items(db, f)


@router.get("/meta")
async def meta(db: DbSession, _: Reader) -> dict[str, Any]:
    return await item_studio.meta(db)


@router.get("/preview-profiles")
async def preview_profiles(db: DbSession, _: Reader) -> list[dict[str, Any]]:
    cfg = await item_studio.studio_config(db)
    return [p.model_dump(by_alias=True) for p in cfg.preview_profiles]


@router.get("/export")
async def export(
    db: DbSession,
    _: Reader,
    f: Annotated[item_studio.ListFilters, Depends()],
    format: Annotated[Literal["json", "csv"], Query()] = "json",
) -> Response:
    rows = await item_studio.export_rows(db, f)
    if format == "csv":
        return Response(
            item_studio.to_csv(rows),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="items.csv"'},
        )
    return Response(
        json.dumps(rows, ensure_ascii=False, indent=1),
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="items.json"'},
    )


class ImportIn(ApiModel):
    format: Literal["json", "csv"]
    content: str = Field(max_length=5_000_000)
    dry_run: bool = True


@router.post("/import")
async def import_items(body: ImportIn, db: DbSession, ctx: Editor) -> dict[str, Any]:
    if body.format == "json":
        try:
            rows = json.loads(body.content)
        except json.JSONDecodeError as exc:
            raise ValidationFailedError("Invalid JSON", code="invalid_import") from exc
        if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
            raise ValidationFailedError("JSON import must be a list of objects", code="invalid_import")
    else:
        rows = item_studio.parse_csv(body.content)
    out = await item_studio.import_items(db, rows, dry_run=body.dry_run, actor_id=ctx.user_id)
    await db.commit()  # dry-run commits only the audit record
    return out


class GeneratorIn(ApiModel):
    params: GeneratorParams
    commit: bool = False
    confirm_non_dev: bool = False


@router.post("/generator")
async def generator(body: GeneratorIn, db: DbSession, ctx: Editor) -> dict[str, Any]:
    out = await item_studio.generator(
        db, body.params, commit=body.commit, confirm_non_dev=body.confirm_non_dev, actor_id=ctx.user_id
    )
    await db.commit()
    return out


class BulkEditIn(ApiModel):
    codes: list[str] = Field(min_length=1, max_length=500)
    patch: dict[str, Any]
    expected_versions: dict[str, int]


@router.post("/bulk-edit")
async def bulk_edit(body: BulkEditIn, db: DbSession, ctx: Editor) -> dict[str, Any]:
    out = await item_studio.bulk_edit(db, body.codes, body.patch, body.expected_versions, actor_id=ctx.user_id)
    await db.commit()
    return {"updated": out}


class BulkL10nIn(ApiModel):
    codes: list[str] = Field(min_length=1, max_length=500)
    locale: Literal["en", "tr", "zh-CN", "es"]
    status: Literal["draft", "reviewed", "published"]


@router.post("/bulk-translation-status")
async def bulk_translation_status(body: BulkL10nIn, db: DbSession, ctx: Translator) -> dict[str, int]:
    n = await item_studio.bulk_translation_status(
        db, body.codes, body.locale, body.status, actor_id=ctx.user_id, can_review=ctx.has("localization.review")
    )
    await db.commit()
    return {"changed": n}


@router.get("/compare")
async def compare(
    db: DbSession, _: Reader, a: Annotated[str, Query(max_length=96)], b: Annotated[str, Query(max_length=96)]
) -> dict[str, Any]:
    return await item_studio.compare(db, a, b)


@router.get("/{code}")
async def inspector(code: str, db: DbSession, _: Reader) -> dict[str, Any]:
    return await item_studio.inspector(db, code)


class TextIn(ApiModel):
    value: str = Field(max_length=4000)
    status: Literal["draft", "reviewed", "published"] = "draft"
    expected_version: int | None = Field(default=None, ge=0)


@router.put("/{code}/texts/{field}/{locale}")
async def set_text(
    code: str,
    field: Literal["name", "description", "short_description", "lore"],
    locale: Literal["en", "tr", "zh-CN", "es"],
    body: TextIn,
    db: DbSession,
    ctx: Translator,
) -> dict[str, Any]:
    out = await item_studio.set_text(
        db, code, field, locale, body.value, body.status, body.expected_version,
        actor_id=ctx.user_id, can_review=ctx.has("localization.review"),
    )  # fmt: skip
    await db.commit()
    return out


class CloneIn(ApiModel):
    new_code: str = Field(max_length=96)


@router.post("/{code}/clone", status_code=201)
async def clone(code: str, body: CloneIn, db: DbSession, ctx: Editor) -> dict[str, Any]:
    out = await item_studio.clone(db, code, body.new_code, actor_id=ctx.user_id)
    await db.commit()
    return out


class PreviewIn(ApiModel):
    profile: str = Field(max_length=32)
    seed: int = Field(default=1, ge=0, le=2**62)


@router.post("/{code}/preview")
async def preview(code: str, body: PreviewIn, db: DbSession, ctx: Reader) -> dict[str, Any]:
    out = await item_studio.preview(db, code, body.profile, actor_id=ctx.user_id, seed=body.seed)
    await db.rollback()
    return out
