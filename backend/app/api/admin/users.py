from typing import Annotated, Any

from fastapi import APIRouter, Query
from pydantic import Field
from sqlalchemy import func, select

from app.api.deps import DbSession, require
from app.core.errors import NotFoundError
from app.models.auth import AuditLog, User
from app.schemas.common import ApiModel
from app.services import rbac
from app.services.auth import AuthContext

router = APIRouter(prefix="/admin", tags=["admin:users"])


class RoleChangeIn(ApiModel):
    role: str = Field(max_length=32)


@router.get("/users")
async def search_users(
    db: DbSession,
    _: Annotated[AuthContext, require("user.view")],
    q: Annotated[str | None, Query(max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    conds = [User.deleted_at.is_(None)]
    if q:
        conds.append(User.email.like(f"%{q.lower()}%"))
    total = (await db.execute(select(func.count()).select_from(User).where(*conds))).scalar_one()
    rows = (
        await db.execute(
            select(User.id, User.email, User.status, User.created_at)
            .where(*conds)
            .order_by(User.id)
            .limit(limit)
            .offset(offset)
        )
    ).all()
    items = []
    for r in rows:
        roles, _perms, _rank, _staff = await rbac.user_roles_and_permissions(db, r.id)
        items.append({"id": r.id, "email": r.email, "status": r.status, "created_at": r.created_at, "roles": roles})
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.post("/users/{user_id}/roles", status_code=204)
async def grant_role(
    user_id: int, body: RoleChangeIn, db: DbSession, ctx: Annotated[AuthContext, require("user.manage_roles")]
) -> None:
    if (await db.get(User, user_id)) is None:
        raise NotFoundError("User not found")
    await rbac.assign_role(db, user_id=user_id, role_code=body.role, actor_id=ctx.user_id, actor_rank=ctx.rank)
    await db.commit()


@router.delete("/users/{user_id}/roles/{role}", status_code=204)
async def revoke_role(
    user_id: int, role: str, db: DbSession, ctx: Annotated[AuthContext, require("user.manage_roles")]
) -> None:
    await rbac.revoke_role(db, user_id=user_id, role_code=role, actor_id=ctx.user_id, actor_rank=ctx.rank)
    await db.commit()


@router.get("/audit")
async def list_audit(
    db: DbSession,
    _: Annotated[AuthContext, require("audit.view")],
    entity_type: str | None = None,
    entity_id: str | None = None,
    actor_user_id: int | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    before_id: int | None = None,
) -> dict[str, Any]:
    conds = []
    if entity_type:
        conds.append(AuditLog.entity_type == entity_type)
    if entity_id:
        conds.append(AuditLog.entity_id == entity_id)
    if actor_user_id:
        conds.append(AuditLog.actor_user_id == actor_user_id)
    if before_id:
        conds.append(AuditLog.id < before_id)
    rows = list((await db.execute(select(AuditLog).where(*conds).order_by(AuditLog.id.desc()).limit(limit))).scalars())
    items = [
        {
            "id": r.id,
            "actor_user_id": r.actor_user_id,
            "action": r.action,
            "entity_type": r.entity_type,
            "entity_id": r.entity_id,
            "before": r.before,
            "after": r.after,
            "meta": r.meta,
            "correlation_id": r.correlation_id,
            "created_at": r.created_at,
        }
        for r in rows
    ]
    return {"items": items, "next_before_id": items[-1]["id"] if len(items) == limit else None}
