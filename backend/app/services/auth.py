"""Accounts and server-side cookie sessions (see ADR-0007)."""

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import rate_limit
from app.core.config import get_settings
from app.core.errors import ConflictError, UnauthorizedError, ValidationFailedError
from app.core.security import hash_password, needs_rehash, new_token, token_hash, verify_password
from app.models.auth import AuthSession, User, UserSettings
from app.services import audit, rbac

EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,189}\.[^@\s]{2,63}$")
PASSWORD_MIN, PASSWORD_MAX = 10, 128


@dataclass(slots=True)
class AuthContext:
    user_id: int
    email: str
    session_id: int
    csrf_hash: str
    roles: list[str] = field(default_factory=list)
    permissions: set[str] = field(default_factory=set)
    rank: int = 0
    is_staff: bool = False
    locale: str = "en"
    step_up_at: datetime | None = None

    def has(self, permission: str) -> bool:
        return permission in self.permissions


@dataclass(slots=True)
class IssuedSession:
    token: str
    csrf_token: str
    expires_at: datetime
    user_id: int


def now() -> datetime:
    return datetime.now(UTC)


def normalize_email(email: str) -> str:
    return email.strip().lower()


def validate_credentials(email: str, password: str) -> str:
    email_n = normalize_email(email)
    if not EMAIL_RE.match(email_n):
        raise ValidationFailedError("Invalid email address", code="invalid_email")
    if not PASSWORD_MIN <= len(password) <= PASSWORD_MAX:
        raise ValidationFailedError(f"Password must be {PASSWORD_MIN}-{PASSWORD_MAX} characters", code="weak_password")
    if password.lower() == email_n or password.lower() in email_n:
        raise ValidationFailedError("Password must not contain the email address", code="weak_password")
    if len(set(password)) < 4:
        raise ValidationFailedError("Password is too simple", code="weak_password")
    return email_n


async def register(db: AsyncSession, *, email: str, password: str, locale: str, ip: str | None) -> User:
    email_n = validate_credentials(email, password)
    user = User(email=email_n, password_hash=hash_password(password))
    db.add(user)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise ConflictError("An account with this email already exists", code="email_taken") from exc
    db.add(UserSettings(user_id=user.id, locale=locale))
    await rbac.assign_role(db, user_id=user.id, role_code="player", actor_id=None, actor_rank=None)
    await audit.record(db, actor_id=user.id, action="user.register", entity_type="user", entity_id=user.id, ip=ip)
    return user


async def issue_session(db: AsyncSession, user_id: int, *, ip: str | None, user_agent: str | None) -> IssuedSession:
    s = get_settings()
    token, csrf = new_token(), new_token()
    expires = now() + timedelta(days=s.session_ttl_days)
    db.add(
        AuthSession(
            user_id=user_id,
            token_hash=token_hash(token),
            csrf_hash=token_hash(csrf),
            expires_at=expires,
            ip=ip,
            user_agent=(user_agent or "")[:300] or None,
        )
    )
    await db.flush()
    return IssuedSession(token=token, csrf_token=csrf, expires_at=expires, user_id=user_id)


async def login(
    db: AsyncSession, *, email: str, password: str, ip: str | None, user_agent: str | None
) -> IssuedSession:
    s = get_settings()
    email_n = normalize_email(email)
    await rate_limit.hit(f"login:ip:{ip}", s.rl_login_ip)
    await rate_limit.hit(f"login:email:{email_n}", s.rl_login_email)
    user = (
        await db.execute(select(User).where(User.email == email_n, User.deleted_at.is_(None)).with_for_update())
    ).scalar_one_or_none()
    ok = verify_password(user.password_hash if user else None, password)
    generic = UnauthorizedError("Invalid email or password", code="invalid_credentials")
    if user is None:
        raise generic
    if user.locked_until and user.locked_until > now():
        raise UnauthorizedError(
            "Account temporarily locked", code="account_locked", details={"locked_until": user.locked_until.isoformat()}
        )
    if not ok:
        user.failed_login_count += 1
        if user.failed_login_count >= s.login_max_failures_before_lock:
            user.locked_until = now() + timedelta(minutes=s.login_lock_minutes)
            user.failed_login_count = 0
        await audit.record(
            db, actor_id=user.id, action="user.login_failed", entity_type="user", entity_id=user.id, ip=ip
        )
        await db.commit()
        raise generic
    if user.status != "active":
        raise UnauthorizedError("Account disabled", code="account_disabled")
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    user.failed_login_count, user.locked_until, user.last_login_at = 0, None, now()
    issued = await issue_session(db, user.id, ip=ip, user_agent=user_agent)
    await rate_limit.reset(f"login:email:{email_n}", s.rl_login_email)
    return issued


async def resolve_session(db: AsyncSession, token: str | None) -> AuthContext | None:
    if not token or len(token) > 128:
        return None
    row = (
        await db.execute(
            select(AuthSession, User.email, User.status, UserSettings.locale)
            .join(User, User.id == AuthSession.user_id)
            .join(UserSettings, UserSettings.user_id == User.id, isouter=True)
            .where(
                AuthSession.token_hash == token_hash(token), AuthSession.revoked_at.is_(None), User.deleted_at.is_(None)
            )
        )
    ).first()
    if row is None:
        return None
    sess, email, status, locale = row
    current = now()
    if sess.expires_at <= current or status != "active":
        return None
    if (current - sess.last_seen_at).total_seconds() > get_settings().session_touch_seconds:
        await db.execute(update(AuthSession).where(AuthSession.id == sess.id).values(last_seen_at=current))
        await db.commit()
    roles, perms, rank, staff = await rbac.user_roles_and_permissions(db, sess.user_id)
    return AuthContext(
        user_id=sess.user_id,
        email=email,
        session_id=sess.id,
        csrf_hash=sess.csrf_hash,
        roles=roles,
        permissions=perms,
        rank=rank,
        is_staff=staff,
        locale=locale or "en",
        step_up_at=sess.step_up_at,
    )


async def logout(db: AsyncSession, session_id: int) -> None:
    await db.execute(update(AuthSession).where(AuthSession.id == session_id).values(revoked_at=now()))


async def revoke_all_sessions(db: AsyncSession, user_id: int) -> None:
    await db.execute(
        update(AuthSession)
        .where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=now())
    )
