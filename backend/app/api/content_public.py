"""Player-facing content reads: published data only (drafts never leak here)."""

from typing import Any

from fastapi import APIRouter

from app.api.deps import DbSession, LocaleDep
from app.services.content import service

router = APIRouter(prefix="/content", tags=["content"])


@router.get("/version")
async def content_version(db: DbSession) -> dict[str, Any]:
    """Current global content release; clients use it to invalidate cached catalogs."""
    return {"release_version": await service.current_release_version(db)}


@router.get("/races")
async def list_races(db: DbSession, locale: LocaleDep) -> list[dict[str, Any]]:
    from app.services import races

    return await races.race_cards(db, locale)
