"""Seed helpers for canonical content: create+publish missing entities; never clobber admin-tuned live data."""

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.content import service
from app.services.content.registry import ContentType


async def ensure_published(
    db: AsyncSession, ct: ContentType, code: str, data: dict[str, Any], *, label: str = "canonical seed"
) -> bool:
    """Returns True when created+published. Existing entities are left untouched (idempotent)."""
    exists = (await db.execute(select(ct.model.id).where(ct.model.code == code))).first()
    if exists:
        return False
    await service.create(db, ct, code=code, data=data, actor_id=None)
    await service.publish(db, [(ct, code)], actor_id=None, label=label, acknowledge_warnings=True)
    return True
