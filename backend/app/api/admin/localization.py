from typing import Annotated, Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from sqlalchemy import ColumnElement, and_, exists, func, or_, select

from app.api.deps import DbSession, require
from app.core.errors import AppError, PermissionDeniedError
from app.localization import service
from app.localization.locales import normalize_text
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


@router.get("/namespaces")
async def namespaces(db: DbSession, _: Annotated[AuthContext, require("localization.edit")]) -> list[dict[str, Any]]:
    rows = await db.execute(
        select(LocalizationKey.namespace, func.count())
        .where(LocalizationKey.deleted_at.is_(None))
        .group_by(LocalizationKey.namespace)
        .order_by(LocalizationKey.namespace)
    )
    return [{"namespace": ns, "keys": int(n)} for ns, n in rows.all()]


@router.get("/dashboard")
async def dashboard(
    db: DbSession, _: Annotated[AuthContext, require("localization.edit")], namespace: str | None = None
) -> dict[str, Any]:
    """Per-locale completion % plus missing / draft / reviewed / published counts."""
    data = await service.completeness(db, namespace)
    out = {}
    for loc, c in data.items():
        done = c.get("reviewed", 0) + c.get("published", 0)
        present = done + c.get("draft", 0)
        out[loc] = {
            **c,
            "present_pct": round(100 * present / c["total"], 1) if c["total"] else 100.0,
            "reviewed_pct": round(100 * done / c["total"], 1) if c["total"] else 100.0,
        }
    return {"namespace": namespace, "locales": out}


EXPORT_LIMIT = 20_000


@router.get("/export")
async def export(
    db: DbSession,
    _: Annotated[AuthContext, require("localization.edit")],
    namespace: str | None = None,
    fmt: Annotated[str, Query(alias="format", pattern="^(json|csv)$")] = "json",
) -> Any:
    from fastapi.responses import Response

    conds: list[ColumnElement[bool]] = [LocalizationKey.deleted_at.is_(None)]
    if namespace:
        conds.append(LocalizationKey.namespace == namespace)
    keys = list(
        (
            await db.execute(
                select(LocalizationKey.key).where(*conds).order_by(LocalizationKey.key).limit(EXPORT_LIMIT)
            )
        ).scalars()
    )
    values = await service.get_all_locales(db, keys)
    rows = [
        {"key": k, "locale": loc, "value": v["value"], "status": v["status"]}
        for k in keys
        for loc, v in values[k].items()
    ]
    if fmt == "json":
        return {"namespace": namespace, "rows": rows}
    import csv
    import io

    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=["key", "locale", "value", "status"])
    w.writeheader()
    for r in rows:
        # neutralize spreadsheet formula injection
        w.writerow({**r, "value": f"'{r['value']}" if str(r["value"]).startswith(("=", "+", "-", "@")) else r["value"]})
    return Response(buf.getvalue(), media_type="text/csv; charset=utf-8")


class ImportRow(BaseModel):
    key: str = Field(max_length=200)
    locale: str = Field(pattern="^(en|tr|zh-CN|es)$")
    value: str = Field(max_length=5000)
    status: str = Field(default="draft", pattern="^(draft|reviewed|published)$")


class ImportIn(BaseModel):
    rows: list[ImportRow] = Field(min_length=1, max_length=5000)
    dry_run: bool = True
    overwrite_reviewed: bool = False


@router.post("/import")
async def import_rows(
    body: ImportIn, db: DbSession, ctx: Annotated[AuthContext, require("localization.edit")]
) -> dict[str, Any]:
    """Validated bulk import. Never overwrites reviewed/published text unless a reviewer asks explicitly."""
    can_review = ctx.has("localization.review")
    if body.overwrite_reviewed and not can_review:
        raise PermissionDeniedError("Overwriting reviewed translations requires localization.review")
    wanted = list({r.key for r in body.rows})
    known = set(
        (
            await db.execute(
                select(LocalizationKey.key).where(LocalizationKey.key.in_(wanted), LocalizationKey.deleted_at.is_(None))
            )
        ).scalars()
    )
    current = await service.get_all_locales(db, [k for k in wanted if k in known])
    summary = {"created": 0, "updated": 0, "unchanged": 0, "skipped_reviewed": 0, "unknown_key": 0, "errors": []}
    for r in body.rows:
        cur = current.get(r.key)
        if cur is None:
            summary["unknown_key"] += 1  # type: ignore[operator]
            continue
        status = r.status if can_review else "draft"
        old = cur[r.locale]
        if old["value"] == normalize_text(r.value) and old["status"] == status:
            summary["unchanged"] += 1  # type: ignore[operator]
            continue
        if old["status"] in ("reviewed", "published") and old["value"] and not body.overwrite_reviewed:
            summary["skipped_reviewed"] += 1  # type: ignore[operator]
            continue
        summary["updated" if old["version"] else "created"] += 1  # type: ignore[operator]
        if not body.dry_run:
            try:
                await service.set_value(
                    db, key=r.key, locale=r.locale, value=r.value, status=status,
                    expected_version=old["version"] or None, actor_id=ctx.user_id,
                )  # fmt: skip
            except AppError as exc:  # report per-row problems, keep going
                summary["errors"].append({"key": r.key, "locale": r.locale, "error": getattr(exc, "code", "invalid")})  # type: ignore[attr-defined]
    if not body.dry_run:
        await audit.record(
            db, actor_id=ctx.user_id, action="localization.import", entity_type="localization",
            meta={k: v for k, v in summary.items() if k != "errors"},
        )  # fmt: skip
        await db.commit()
    return {"dry_run": body.dry_run, **summary}
