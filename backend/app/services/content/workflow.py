"""Publish workflow on top of the content service: Draft → Validation → Review → Published → Archived.

Reviews bind to an `edit_version`; editing again makes an approval stale. When `content_review_required` is on,
publishing requires an approved review by someone other than the requester (four-eyes)."""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import ConflictError, PermissionDeniedError, ValidationFailedError
from app.models.content import ContentReview
from app.services import audit
from app.services.content import references
from app.services.content import service as content
from app.services.content.registry import ContentType


async def _current(db: AsyncSession, ct: ContentType, code: str) -> tuple[Any, int]:
    """(row, edit_version); reviews are keyed by (revision_no, edit_version) so they never outlive an edit."""
    row = await content.get_row(db, ct, code)
    draft = await content.get_draft(db, ct, row.id)
    return row, content.edit_version(row, draft)


async def review_state(db: AsyncSession, ct: ContentType, code: str) -> dict[str, Any]:
    row, version = await _current(db, ct, code)
    rev = (
        await db.execute(
            select(ContentReview).where(
                ContentReview.entity_type == ct.entity_type,
                ContentReview.entity_id == row.id,
                ContentReview.base_revision_no == row.revision_no,
                ContentReview.edit_version == version,
            )
        )
    ).scalar_one_or_none()
    pending = row.revision_no == 0 or (await content.get_draft(db, ct, row.id)) is not None
    review = rev.status if rev else None
    if row.status == "archived":
        stage = "archived"
    elif not pending:
        stage = "published"
    else:
        stage = {"requested": "review", "approved": "approved"}.get(review or "", "draft")
    return {
        "stage": stage,
        "edit_version": version,
        "review": None
        if rev is None
        else {
            "status": rev.status,
            "requested_by": rev.requested_by,
            "reviewed_by": rev.reviewed_by,
            "note": rev.note,
            "reviewed_at": rev.reviewed_at.isoformat() if rev.reviewed_at else None,
        },
        "review_required": get_settings().content_review_required,
    }


async def request_review(db: AsyncSession, ct: ContentType, code: str, *, actor_id: int) -> dict[str, Any]:
    row, version = await _current(db, ct, code)
    issues = await content.validate(db, ct, code, (await content.working_view(db, ct, row))["data"])
    if any(i.level == "error" for i in issues):
        raise ValidationFailedError(
            "Fix validation errors before review", code="publish_blocked", details=[i.as_dict() for i in issues]
        )
    await db.execute(
        insert(ContentReview)
        .values(
            entity_type=ct.entity_type,
            entity_id=row.id,
            base_revision_no=row.revision_no,
            edit_version=version,
            status="requested",
            requested_by=actor_id,
        )
        .on_conflict_do_update(
            index_elements=["entity_type", "entity_id", "base_revision_no", "edit_version"],
            set_={
                "status": "requested",
                "requested_by": actor_id,
                "reviewed_by": None,
                "note": None,
                "reviewed_at": None,
            },
        )
    )
    await audit.record(
        db,
        actor_id=actor_id,
        action="content.review.request",
        entity_type=ct.entity_type,
        entity_id=code,
        meta={"edit_version": version},
    )
    return await review_state(db, ct, code)


async def decide(
    db: AsyncSession, ct: ContentType, code: str, *, actor_id: int, approve: bool, note: str | None
) -> dict[str, Any]:
    row, version = await _current(db, ct, code)
    rev = (
        await db.execute(
            select(ContentReview)
            .where(
                ContentReview.entity_type == ct.entity_type,
                ContentReview.entity_id == row.id,
                ContentReview.base_revision_no == row.revision_no,
                ContentReview.edit_version == version,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if rev is None or rev.status != "requested":
        raise ConflictError("No pending review for the current version", code="no_pending_review")
    if rev.requested_by == actor_id:
        raise PermissionDeniedError("Reviews need a second person")
    rev.status = "approved" if approve else "changes_requested"
    rev.reviewed_by, rev.note, rev.reviewed_at = actor_id, note, datetime.now(UTC)
    await db.flush()
    await audit.record(
        db, actor_id=actor_id, action=f"content.review.{'approve' if approve else 'reject'}",
        entity_type=ct.entity_type, entity_id=code, meta={"edit_version": version, "note": note},
    )  # fmt: skip
    return await review_state(db, ct, code)


async def check_publishable(db: AsyncSession, items: list[tuple[ContentType, str]]) -> None:
    if not get_settings().content_review_required:
        return
    missing = []
    for ct, code in items:
        state = await review_state(db, ct, code)
        if state["stage"] != "approved":
            missing.append(f"{ct.entity_type}:{code}")
    if missing:
        raise ConflictError(
            "Approved review required before publishing", code="review_required", details={"items": missing}
        )


async def guard_references(db: AsyncSession, ct: ContentType, code: str, *, acknowledged: bool) -> dict[str, Any]:
    refs = await references.incoming(db, ct.entity_type, code, limit=20)
    if refs["total"] and not acknowledged:
        raise ConflictError(
            f"{code} is referenced by {refs['total']} entities",
            code="referenced",
            details={"by_type": refs["by_type"], "items": refs["items"]},
        )
    return refs
