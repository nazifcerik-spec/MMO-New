import asyncio
import time
from typing import Any

from fastapi import APIRouter, Response
from sqlalchemy import text

from app.core.config import get_settings
from app.db.redis import get_redis
from app.db.session import get_engine

router = APIRouter(tags=["health"])


async def _check_db() -> dict[str, Any]:
    start = time.perf_counter()
    try:
        async with get_engine().connect() as conn:
            await asyncio.wait_for(conn.execute(text("SELECT 1")), timeout=3)
        return {"status": "ok", "latency_ms": round((time.perf_counter() - start) * 1000, 2)}
    except Exception as exc:
        return {"status": "error", "error": type(exc).__name__}


async def _check_redis() -> dict[str, Any]:
    start = time.perf_counter()
    try:
        await asyncio.wait_for(get_redis().ping(), timeout=3)
        return {"status": "ok", "latency_ms": round((time.perf_counter() - start) * 1000, 2)}
    except Exception as exc:
        return {"status": "error", "error": type(exc).__name__}


@router.get("/health/live")
async def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health")
async def health(response: Response) -> dict[str, Any]:
    db, redis = await asyncio.gather(_check_db(), _check_redis())
    ok = db["status"] == "ok" and redis["status"] == "ok"
    if not ok:
        response.status_code = 503
    return {
        "status": "ok" if ok else "degraded",
        "env": get_settings().env,
        "checks": {"database": db, "redis": redis},
    }


@router.get("/health/ready")
async def ready(response: Response) -> dict[str, Any]:
    return await health(response)
