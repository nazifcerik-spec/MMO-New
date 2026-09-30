"""Role/permission seeding and checks (deny by default)."""

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.content.loader import load_yaml
from app.core.errors import NotFoundError, PermissionDeniedError
from app.models.auth import Permission, Role, RolePermission, UserRole
from app.services import audit

WILDCARD = "*"


async def seed_rbac(db: AsyncSession) -> int:
    doc = load_yaml("system/rbac.yaml")
    written = 0
    for code, desc in doc["permissions"].items():
        await db.execute(
            insert(Permission)
            .values(code=code, description=desc)
            .on_conflict_do_update(index_elements=["code"], set_={"description": desc})
        )
        written += 1
    perms = {p.code: p.id for p in (await db.execute(select(Permission))).scalars()}
    for code, spec in doc["roles"].items():
        await db.execute(
            insert(Role)
            .values(code=code, rank=spec["rank"], is_staff=spec["staff"])
            .on_conflict_do_update(index_elements=["code"], set_={"rank": spec["rank"], "is_staff": spec["staff"]})
        )
        role_id = (await db.execute(select(Role.id).where(Role.code == code))).scalar_one()
        wanted = set(perms) if WILDCARD in spec["permissions"] else set(spec["permissions"])
        unknown = wanted - set(perms)
        if unknown:
            raise ValueError(f"role {code} references unknown permissions {sorted(unknown)}")
        await db.execute(
            delete(RolePermission).where(
                RolePermission.role_id == role_id, RolePermission.permission_id.notin_([perms[p] for p in wanted])
            )
        )
        if wanted:
            await db.execute(
                insert(RolePermission)
                .values([{"role_id": role_id, "permission_id": perms[p]} for p in wanted])
                .on_conflict_do_nothing()
            )
        written += 1
    return written


async def user_roles_and_permissions(db: AsyncSession, user_id: int) -> tuple[list[str], set[str], int, bool]:
    """Returns (role codes, permission codes, max rank, is_staff)."""
    rows = (
        await db.execute(
            select(Role.code, Role.rank, Role.is_staff, Permission.code)
            .join(UserRole, UserRole.role_id == Role.id)
            .join(RolePermission, RolePermission.role_id == Role.id, isouter=True)
            .join(Permission, Permission.id == RolePermission.permission_id, isouter=True)
            .where(UserRole.user_id == user_id)
        )
    ).all()
    roles = sorted({r[0] for r in rows})
    perms = {r[3] for r in rows if r[3]}
    rank = max((r[1] for r in rows), default=0)
    staff = any(r[2] for r in rows)
    return roles, perms, rank, staff


async def assign_role(
    db: AsyncSession, *, user_id: int, role_code: str, actor_id: int | None, actor_rank: int | None
) -> None:
    role = (await db.execute(select(Role).where(Role.code == role_code))).scalar_one_or_none()
    if role is None:
        raise NotFoundError(f"Unknown role {role_code}")
    # Privilege escalation guard: only roles strictly below the actor's rank may be granted (system = None).
    if actor_rank is not None and role.rank >= actor_rank:
        raise PermissionDeniedError("Cannot grant a role at or above your own rank", code="rank_too_low")
    await db.execute(
        insert(UserRole).values(user_id=user_id, role_id=role.id, granted_by=actor_id).on_conflict_do_nothing()
    )
    await audit.record(
        db, actor_id=actor_id, action="role.grant", entity_type="user", entity_id=user_id, after={"role": role_code}
    )


async def revoke_role(db: AsyncSession, *, user_id: int, role_code: str, actor_id: int, actor_rank: int) -> None:
    role = (await db.execute(select(Role).where(Role.code == role_code))).scalar_one_or_none()
    if role is None:
        raise NotFoundError(f"Unknown role {role_code}")
    if role.rank >= actor_rank:
        raise PermissionDeniedError("Cannot revoke a role at or above your own rank", code="rank_too_low")
    if role.code == "player":
        raise PermissionDeniedError("The player role cannot be revoked", code="protected_role")
    await db.execute(delete(UserRole).where(UserRole.user_id == user_id, UserRole.role_id == role.id))
    await audit.record(
        db, actor_id=actor_id, action="role.revoke", entity_type="user", entity_id=user_id, before={"role": role_code}
    )
