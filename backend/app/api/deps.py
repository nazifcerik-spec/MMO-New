from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ValidationFailedError
from app.db.session import get_sessionmaker
from app.localization.locales import (
    DEFAULT_LOCALE,
    LOCALE_COOKIE,
    SUPPORTED_LOCALES,
    is_supported,
    parse_accept_language,
)


async def get_db() -> AsyncIterator[AsyncSession]:
    async with get_sessionmaker()() as session:
        yield session


DbSession = Annotated[AsyncSession, Depends(get_db)]


def get_locale(
    request: Request, locale: Annotated[str | None, Query(description="en | tr | zh-CN | es")] = None
) -> str:
    """Resolution order: ?locale= (strict) -> cookie -> Accept-Language -> en."""
    if locale is not None:
        if not is_supported(locale):
            raise ValidationFailedError(
                f"Unsupported locale '{locale}'",
                code="invalid_locale",
                details={"supported": list(SUPPORTED_LOCALES)},
            )
        return locale
    cookie = request.cookies.get(LOCALE_COOKIE)
    if is_supported(cookie):
        assert cookie is not None
        return cookie
    return parse_accept_language(request.headers.get("accept-language")) or DEFAULT_LOCALE


LocaleDep = Annotated[str, Depends(get_locale)]


# ---------------------------------------------------------------- auth / RBAC
from fastapi import Request as _Request  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.errors import PermissionDeniedError, UnauthorizedError  # noqa: E402
from app.core.security import token_hash, tokens_equal  # noqa: E402
from app.services.auth import AuthContext, resolve_session  # noqa: E402

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def client_ip(request: _Request) -> str | None:
    return request.client.host if request.client else None


def _check_origin(request: _Request) -> None:
    origin = request.headers.get("origin")
    if origin and origin not in get_settings().cors_origins and origin != str(request.base_url).rstrip("/"):
        raise PermissionDeniedError("Cross-origin request rejected", code="bad_origin")


async def get_optional_auth(request: _Request, db: DbSession) -> AuthContext | None:
    return await resolve_session(db, request.cookies.get(get_settings().session_cookie))


async def get_auth(request: _Request, db: DbSession) -> AuthContext:
    ctx = await get_optional_auth(request, db)
    if ctx is None:
        raise UnauthorizedError("Authentication required")
    if request.method not in SAFE_METHODS:
        _check_origin(request)
        header = request.headers.get("x-csrf-token", "")
        if not header or not tokens_equal(token_hash(header), ctx.csrf_hash):
            raise PermissionDeniedError("Missing or invalid CSRF token", code="csrf_failed")
    return ctx


OptionalAuth = Annotated[AuthContext | None, Depends(get_optional_auth)]
Auth = Annotated[AuthContext, Depends(get_auth)]


def require(*permissions: str):  # type: ignore[no-untyped-def]
    """Dependency factory: all listed permissions required (deny by default)."""

    async def _dep(ctx: Auth) -> AuthContext:
        missing = [p for p in permissions if p not in ctx.permissions]
        if missing:
            raise PermissionDeniedError("Insufficient permissions", details={"missing": missing})
        return ctx

    return Depends(_dep)
