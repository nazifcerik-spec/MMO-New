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
