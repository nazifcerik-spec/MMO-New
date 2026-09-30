from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import get_correlation_id
from app.models.auth import AuditLog


async def record(
    db: AsyncSession,
    *,
    actor_id: int | None,
    action: str,
    entity_type: str,
    entity_id: str | int | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    meta: dict[str, Any] | None = None,
    ip: str | None = None,
) -> AuditLog:
    """Append an audit record in the caller's transaction (committed or rolled back with the change itself)."""
    row = AuditLog(
        actor_user_id=actor_id,
        action=action,
        entity_type=entity_type,
        entity_id=None if entity_id is None else str(entity_id),
        before=before,
        after=after,
        meta=meta,
        correlation_id=get_correlation_id(),
        ip=ip,
    )
    db.add(row)
    return row


def diff(before: dict[str, Any], after: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Shallow field diff {field: {"from": x, "to": y}} for audit metadata."""
    keys = set(before) | set(after)
    return {k: {"from": before.get(k), "to": after.get(k)} for k in sorted(keys) if before.get(k) != after.get(k)}
