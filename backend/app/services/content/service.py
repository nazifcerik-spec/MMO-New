"""Generic content lifecycle: draft → validate → publish (release + immutable revision) → disable/archive,
history, diff and rollback-as-new-revision. Live rows change only on publish."""

import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError
from sqlalchemy import ColumnElement, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError, ValidationFailedError
from app.models.content import ContentDraft, ContentMixin, ContentRelease, ContentRevision
from app.services import audit
from app.services.content.registry import ContentType, Issue

CODE_RE = re.compile(r"^[a-z][a-z0-9_]{1,95}$")
RELEASE_LOCK_KEY = 71_000_001


def _now() -> datetime:
    return datetime.now(UTC)


def data_hash(data: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


async def get_row(db: AsyncSession, ct: ContentType, code: str, *, for_update: bool = False) -> Any:
    stmt = select(ct.model).where(ct.model.code == code, ct.model.deleted_at.is_(None))
    if for_update:
        stmt = stmt.with_for_update()
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None:
        raise NotFoundError(f"{ct.entity_type} '{code}' not found")
    return row


async def get_draft(db: AsyncSession, ct: ContentType, row_id: int, *, for_update: bool = False) -> ContentDraft | None:
    stmt = select(ContentDraft).where(ContentDraft.entity_type == ct.entity_type, ContentDraft.entity_id == row_id)
    if for_update:
        stmt = stmt.with_for_update()
    return (await db.execute(stmt)).scalar_one_or_none()


def edit_version(row: ContentMixin, draft: ContentDraft | None) -> int:
    """Optimistic token the editor must echo back: row.version for never-published rows, else draft version."""
    if row.revision_no == 0:
        return row.version
    return draft.version if draft else 0


async def working_view(db: AsyncSession, ct: ContentType, row: Any) -> dict[str, Any]:
    draft = await get_draft(db, ct, row.id)
    return {
        "code": row.code,
        "status": row.status,
        "revision_no": row.revision_no,
        "name_key": row.name_key,
        "description_key": row.description_key,
        "published_at": row.published_at,
        "has_pending_changes": draft is not None or row.revision_no == 0,
        "edit_version": edit_version(row, draft),
        "data": draft.data if draft else ct.to_data(row),
        "live_data": ct.to_data(row) if row.revision_no > 0 else None,
    }


def _validate_schema(ct: ContentType, data: dict[str, Any]) -> dict[str, Any]:
    try:
        return ct.data_schema.model_validate(data).model_dump(mode="json")
    except ValidationError as exc:
        issues = [
            Issue("error", "schema", e["msg"], ".".join(str(p) for p in e["loc"])).as_dict() for e in exc.errors()
        ]
        raise ValidationFailedError("Content data is invalid", code="invalid_content", details=issues) from exc


async def validate(db: AsyncSession, ct: ContentType, code: str, data: dict[str, Any]) -> list[Issue]:
    try:
        clean = ct.data_schema.model_validate(data).model_dump(mode="json")
    except ValidationError as exc:
        return [Issue("error", "schema", e["msg"], ".".join(str(p) for p in e["loc"])) for e in exc.errors()]
    issues: list[Issue] = []
    for v in ct.validators:
        issues.extend(await v(db, code, clean))
    return issues


async def create(
    db: AsyncSession,
    ct: ContentType,
    *,
    code: str,
    data: dict[str, Any],
    actor_id: int | None,
    description: bool = True,
) -> Any:
    if not CODE_RE.match(code):
        raise ValidationFailedError("Code must be lowercase snake_case (2-96 chars)", code="invalid_code")
    clean = _validate_schema(ct, data)
    row = ct.model(
        code=code,
        name_key=f"{ct.l10n_prefix}.{code}.name",
        description_key=f"{ct.l10n_prefix}.{code}.description" if description else None,
        status="draft",
        revision_no=0,
        created_by=actor_id,
        updated_by=actor_id,
    )
    ct.apply_data(row, clean)
    db.add(row)
    try:
        await db.flush()
    except IntegrityError as exc:
        raise ConflictError(f"{ct.entity_type} code '{code}' already exists", code="duplicate_code") from exc
    await audit.record(
        db, actor_id=actor_id, action="content.create", entity_type=ct.entity_type, entity_id=code, after=clean
    )
    return row


async def update(
    db: AsyncSession, ct: ContentType, *, code: str, data: dict[str, Any], expected_version: int, actor_id: int | None
) -> dict[str, Any]:
    clean = _validate_schema(ct, data)
    row = await get_row(db, ct, code, for_update=True)
    if row.status == "archived":
        raise ConflictError("Archived content is read-only; restore it first", code="archived")
    draft = await get_draft(db, ct, row.id, for_update=True)
    current = edit_version(row, draft)
    if current != expected_version:
        raise ConflictError(
            "Content was modified by someone else",
            code="version_conflict",
            details={"current_version": current, "current_data": draft.data if draft else ct.to_data(row)},
        )
    before = draft.data if draft else ct.to_data(row)
    if row.revision_no == 0:
        ct.apply_data(row, clean)
        row.updated_by = actor_id
    elif draft is None:
        db.add(
            ContentDraft(
                entity_type=ct.entity_type,
                entity_id=row.id,
                data=clean,
                base_revision_no=row.revision_no,
                updated_by=actor_id,
            )
        )
    else:
        draft.data, draft.updated_by = clean, actor_id
    await db.flush()
    await audit.record(
        db,
        actor_id=actor_id,
        action="content.update",
        entity_type=ct.entity_type,
        entity_id=code,
        meta={"diff": audit.diff(before, clean)},
    )
    return await working_view(db, ct, row)


async def discard_draft(db: AsyncSession, ct: ContentType, *, code: str, actor_id: int | None) -> None:
    row = await get_row(db, ct, code)
    draft = await get_draft(db, ct, row.id, for_update=True)
    if draft is not None:
        await db.delete(draft)
        await audit.record(
            db, actor_id=actor_id, action="content.discard_draft", entity_type=ct.entity_type, entity_id=code
        )


async def _new_release(
    db: AsyncSession, *, actor_id: int | None, label: str | None, notes: str | None
) -> ContentRelease:
    await db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": RELEASE_LOCK_KEY})
    last = (await db.execute(select(func.coalesce(func.max(ContentRelease.version_no), 0)))).scalar_one()
    release = ContentRelease(version_no=last + 1, label=label, notes=notes, created_by=actor_id)
    db.add(release)
    await db.flush()
    return release


async def _write_revision(
    db: AsyncSession, ct: ContentType, row: Any, release: ContentRelease, actor_id: int | None, summary: str | None
) -> ContentRevision:
    row.revision_no += 1
    snapshot = {
        "code": row.code,
        "status": row.status,
        "name_key": row.name_key,
        "description_key": row.description_key,
        "data": ct.to_data(row),
    }
    rev = ContentRevision(
        entity_type=ct.entity_type,
        entity_id=row.id,
        entity_code=row.code,
        revision_no=row.revision_no,
        status=row.status,
        data=snapshot,
        data_hash=data_hash(snapshot),
        release_id=release.id,
        change_summary=summary,
        created_by=actor_id,
    )
    db.add(rev)
    return rev


async def publish(
    db: AsyncSession,
    items: list[tuple[ContentType, str]],
    *,
    actor_id: int | None,
    label: str | None = None,
    notes: str | None = None,
    acknowledge_warnings: bool = False,
    summary: str | None = None,
) -> ContentRelease:
    """Publish one or many entities atomically under a single release (publish bundle)."""
    if not items:
        raise ValidationFailedError("Nothing to publish", code="empty_publish")
    staged: list[tuple[ContentType, Any, dict[str, Any], ContentDraft | None]] = []
    problems: dict[str, list[dict[str, str]]] = {}
    for ct, code in items:
        row = await get_row(db, ct, code, for_update=True)
        if row.status == "archived":
            raise ConflictError(f"{code} is archived", code="archived")
        draft = await get_draft(db, ct, row.id, for_update=True)
        data = draft.data if draft else ct.to_data(row)
        issues = await validate(db, ct, code, data)
        blocking = [i for i in issues if i.level == "error" or (i.level == "warning" and not acknowledge_warnings)]
        if blocking:
            problems[f"{ct.entity_type}:{code}"] = [i.as_dict() for i in issues]
        staged.append((ct, row, data, draft))
    if problems:
        raise ValidationFailedError("Publish blocked by validation issues", code="publish_blocked", details=problems)
    release = await _new_release(db, actor_id=actor_id, label=label, notes=notes)
    for ct, row, data, draft in staged:
        before = ct.to_data(row) if row.revision_no > 0 else None
        ct.apply_data(row, _validate_schema(ct, data))
        row.status, row.published_at, row.updated_by = "published", _now(), actor_id
        if draft is not None:
            await db.delete(draft)
        rev = await _write_revision(db, ct, row, release, actor_id, summary)
        await audit.record(
            db,
            actor_id=actor_id,
            action="content.publish",
            entity_type=ct.entity_type,
            entity_id=row.code,
            meta={"release": release.version_no, "revision": rev.revision_no, "diff": audit.diff(before or {}, data)},
        )
    await db.flush()
    return release


async def set_status(db: AsyncSession, ct: ContentType, *, code: str, status: str, actor_id: int | None) -> Any:
    if status not in ("disabled", "archived", "published"):
        raise ValidationFailedError("Invalid target status", code="invalid_status")
    row = await get_row(db, ct, code, for_update=True)
    if row.revision_no == 0:
        raise ConflictError("Never-published content: delete the draft instead", code="not_published")
    if row.status == status:
        return row
    before = row.status
    row.status, row.updated_by = status, actor_id
    release = await _new_release(db, actor_id=actor_id, label=f"{code} → {status}", notes=None)
    await _write_revision(db, ct, row, release, actor_id, f"status {before} → {status}")
    await audit.record(
        db,
        actor_id=actor_id,
        action=f"content.status.{status}",
        entity_type=ct.entity_type,
        entity_id=code,
        before={"status": before},
        after={"status": status},
    )
    await db.flush()
    return row


async def delete_unpublished(db: AsyncSession, ct: ContentType, *, code: str, actor_id: int | None) -> None:
    row = await get_row(db, ct, code, for_update=True)
    if row.revision_no > 0:
        raise ConflictError("Published content cannot be deleted; archive it", code="published_immutable")
    row.deleted_at = _now()
    await audit.record(db, actor_id=actor_id, action="content.delete_draft", entity_type=ct.entity_type, entity_id=code)


async def history(db: AsyncSession, ct: ContentType, code: str) -> list[dict[str, Any]]:
    row = await get_row(db, ct, code)
    revs = (
        await db.execute(
            select(ContentRevision, ContentRelease.version_no)
            .join(ContentRelease, ContentRelease.id == ContentRevision.release_id)
            .where(ContentRevision.entity_type == ct.entity_type, ContentRevision.entity_id == row.id)
            .order_by(ContentRevision.revision_no.desc())
        )
    ).all()
    return [
        {
            "revision_no": r.revision_no,
            "status": r.status,
            "release_version": v,
            "data_hash": r.data_hash,
            "created_by": r.created_by,
            "created_at": r.created_at,
            "change_summary": r.change_summary,
        }
        for r, v in revs
    ]


async def get_revision(db: AsyncSession, ct: ContentType, code: str, revision_no: int) -> ContentRevision:
    row = await get_row(db, ct, code)
    rev = (
        await db.execute(
            select(ContentRevision).where(
                ContentRevision.entity_type == ct.entity_type,
                ContentRevision.entity_id == row.id,
                ContentRevision.revision_no == revision_no,
            )
        )
    ).scalar_one_or_none()
    if rev is None:
        raise NotFoundError(f"Revision {revision_no} not found")
    return rev


def flatten(obj: Any, prefix: str = "") -> dict[str, Any]:
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for k, v in obj.items():
            out.update(flatten(v, f"{prefix}.{k}" if prefix else str(k)))
        return out
    if isinstance(obj, list):
        out = {}
        for i, v in enumerate(obj):
            out.update(flatten(v, f"{prefix}[{i}]"))
        return out or {prefix: []}
    return {prefix: obj}


def diff_data(a: dict[str, Any], b: dict[str, Any]) -> list[dict[str, Any]]:
    fa, fb = flatten(a), flatten(b)
    return [
        {"path": k, "from": fa.get(k), "to": fb.get(k)} for k in sorted(set(fa) | set(fb)) if fa.get(k) != fb.get(k)
    ]


async def diff_revisions(
    db: AsyncSession, ct: ContentType, code: str, from_rev: int, to_rev: int | None
) -> list[dict[str, Any]]:
    a = (await get_revision(db, ct, code, from_rev)).data
    if to_rev is None:  # compare with working copy
        row = await get_row(db, ct, code)
        view = await working_view(db, ct, row)
        b = {**a, "data": view["data"]}
    else:
        b = (await get_revision(db, ct, code, to_rev)).data
    return diff_data(a, b)


async def rollback(
    db: AsyncSession,
    ct: ContentType,
    *,
    code: str,
    revision_no: int,
    actor_id: int | None,
    acknowledge_warnings: bool = False,
) -> ContentRelease:
    """Re-publish the data of an older revision as a NEW revision (history is never rewritten)."""
    rev = await get_revision(db, ct, code, revision_no)
    row = await get_row(db, ct, code, for_update=True)
    draft = await get_draft(db, ct, row.id, for_update=True)
    old = rev.data["data"]
    if draft is None:
        db.add(
            ContentDraft(
                entity_type=ct.entity_type,
                entity_id=row.id,
                data=old,
                base_revision_no=row.revision_no,
                updated_by=actor_id,
            )
        )
    else:
        draft.data = old
    await db.flush()
    return await publish(
        db,
        [(ct, code)],
        actor_id=actor_id,
        label=f"rollback {code} to r{revision_no}",
        acknowledge_warnings=acknowledge_warnings,
        summary=f"rollback to revision {revision_no}",
    )


async def list_admin(
    db: AsyncSession, ct: ContentType, *, status: str | None, search: str | None, limit: int, offset: int
) -> tuple[list[Any], int]:
    conds: list[ColumnElement[bool]] = [ct.model.deleted_at.is_(None)]
    if status:
        conds.append(ct.model.status == status)
    if search:
        conds.append(ct.model.code.ilike(f"%{search}%"))
    total = (await db.execute(select(func.count()).select_from(ct.model).where(*conds))).scalar_one()
    rows: list[Any] = list(
        (await db.execute(select(ct.model).where(*conds).order_by(ct.model.code).limit(limit).offset(offset))).scalars()
    )
    return rows, total


async def list_published(db: AsyncSession, ct: ContentType) -> list[Any]:
    return list(
        (
            await db.execute(
                select(ct.model)
                .where(ct.model.status == "published", ct.model.deleted_at.is_(None))
                .order_by(ct.model.id)
            )
        ).scalars()
    )


async def current_release_version(db: AsyncSession) -> int:
    return int((await db.execute(select(func.coalesce(func.max(ContentRelease.version_no), 0)))).scalar_one())
