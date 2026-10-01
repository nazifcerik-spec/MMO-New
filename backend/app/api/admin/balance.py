from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query
from fastapi.responses import Response
from pydantic import Field

from app.api.deps import DbSession, require
from app.schemas.common import ApiModel
from app.services import audit, simulator, telemetry
from app.services.auth import AuthContext

router = APIRouter(prefix="/admin", tags=["admin:balance"])
Designer = Annotated[AuthContext, require("balance.simulate")]
SECTIONS = ("support", "racial", "specializations", "talents", "items")


@router.post("/balance/simulate")
async def simulate(
    body: simulator.SimParams,
    db: DbSession,
    ctx: Designer,
    fmt: Annotated[Literal["json", "csv"], Query(alias="format")] = "json",
) -> Any:
    """Decision-support simulation in a rolled-back sandbox; never changes balance or game data."""
    result = await simulator.run(db, body)
    await audit.record(
        db, actor_id=ctx.user_id, action="balance.simulate", entity_type="balance", meta=body.model_dump()
    )
    await db.commit()
    if fmt == "csv":
        return Response(simulator.to_csv(result), media_type="text/csv; charset=utf-8")
    return result


Section = Literal["support", "racial", "specializations", "talents", "items"]


def _default_sections() -> list[Section]:
    return ["support", "racial", "items"]


class CheckIn(ApiModel):
    level: int = Field(ge=1, le=1000)
    sections: list[Section] = Field(default_factory=_default_sections, min_length=1)
    fights: int | None = Field(default=None, ge=1, le=40)


@router.post("/balance/check")
async def check(body: CheckIn, db: DbSession, ctx: Designer) -> dict[str, Any]:
    report = await simulator.check(db, level=body.level, sections=tuple(body.sections), fights=body.fights)
    await audit.record(
        db,
        actor_id=ctx.user_id,
        action="balance.check",
        entity_type="balance",
        meta={"level": body.level, "sections": body.sections, "warnings": len(report["warnings"])},
    )
    await db.commit()
    return report


@router.get("/telemetry")
async def telemetry_summary(
    db: DbSession, _: Designer, days: Annotated[int, Query(ge=1, le=90)] = 30
) -> dict[str, Any]:
    return await telemetry.summary(db, days=days)
