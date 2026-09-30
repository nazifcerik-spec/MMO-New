from typing import Annotated, Any

from fastapi import APIRouter, Query
from sqlalchemy import ColumnElement, and_, exists, func, or_, select

from app.api.deps import DbSession, require
from app.core.errors import PermissionDeniedError
from app.localization import service
from app.models.localization import LocalizationKey, LocalizationValue
from app.schemas.i18n import TranslationUpdateIn
from app.services import audit
from app.services.auth import AuthContext

router = APIRouter(prefix="/admin/localization", tags=["admin:localization"])


@router.get("/keys")
async def list_keys(
    db: DbSession,
    _: Annotated[AuthContext, require("localization.edit")],
    namespace: str | None = None,
    search: Annotated[str | None, Query(max_length=100)] = None,
    missing_locale: Annotated[str | None, Query(pattern="^(en|tr|zh-CN|es)$")] = None,
    status: Annotated[str | None, Query(pattern="^(missing|draft|reviewed|published)$")] = None,
    status_locale: Annotated[str | None, Query(pattern="^(en|tr|zh-CN|es)$")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    conds: list[ColumnElement[bool]] = [LocalizationKey.deleted_at.is_(None)]
    if namespace:
        conds.append(LocalizationKey.namespace == namespace)
    if search:
        like = f"%{search.lower()}%"
        conds.append(
            or_(
                func.lower(LocalizationKey.key).like(like),
                exists().where(
                    LocalizationValue.key_id == LocalizationKey.id, func.lower(LocalizationValue.value).like(like)
                ),
            )
        )
    if missing_locale:
        conds.append(
            ~exists().where(
                and_(
                    LocalizationValue.key_id == LocalizationKey.id,
                    LocalizationValue.locale == missing_locale,
                    LocalizationValue.value != "",
                    LocalizationValue.status != "missing",
                )
            )
        )
    if status and status_locale:
        conds.append(
            exists().where(
                and_(
                    LocalizationValue.key_id == LocalizationKey.id,
                    LocalizationValue.locale == status_locale,
                    LocalizationValue.status == status,
                )
            )
        )
    total = (await db.execute(select(func.count()).select_from(LocalizationKey).where(*conds))).scalar_one()
    keys = list(
        (
            await db.execute(
                select(LocalizationKey.key).where(*conds).order_by(LocalizationKey.key).limit(limit).offset(offset)
            )
        ).scalars()
    )
    values = await service.get_all_locales(db, keys)
    return {"items": [{"key": k, "values": values[k]} for k in keys], "total": total, "limit": limit, "offset": offset}


@router.put("/keys/{key}/{locale}")
async def update_translation(
    key: str,
    locale: str,
    body: TranslationUpdateIn,
    db: DbSession,
    ctx: Annotated[AuthContext, require("localization.edit")],
) -> dict[str, Any]:
    if body.status in ("reviewed", "published") and not ctx.has("localization.review"):
        raise PermissionDeniedError("Reviewing/publishing translations requires localization.review")
    before = (await service.get_all_locales(db, [key])).get(key, {}).get(locale)
    row = await service.set_value(
        db,
        key=key,
        locale=locale,
        value=body.value,
        status=body.status,
        expected_version=body.expected_version,
        actor_id=ctx.user_id,
    )
    after = {"value": row.value, "status": row.status, "version": row.version}
    await audit.record(
        db,
        actor_id=ctx.user_id,
        action="localization.update",
        entity_type="localization",
        entity_id=f"{key}:{locale}",
        before=before,
        after=after,
    )
    await db.commit()
    return {"key": key, "locale": locale, **after}


@router.get("/completeness")
async def completeness(
    db: DbSession, _: Annotated[AuthContext, require("localization.edit")], namespace: str | None = None
) -> dict[str, dict[str, int]]:
    return await service.completeness(db, namespace)
