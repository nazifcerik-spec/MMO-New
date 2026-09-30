"""Player-facing content reads: published data only (drafts never leak here)."""

from typing import Any

from fastapi import APIRouter

from app.api.deps import DbSession
from app.services.content import service

router = APIRouter(prefix="/content", tags=["content"])


@router.get("/version")
async def content_version(db: DbSession) -> dict[str, Any]:
    """Current global content release; clients use it to invalidate cached catalogs."""
    return {"release_version": await service.current_release_version(db)}
