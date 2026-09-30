from typing import Annotated

from fastapi import APIRouter, Query, Response

from app.api.deps import DbSession, LocaleDep
from app.core.config import get_settings
from app.core.errors import ValidationFailedError
from app.localization import service
from app.localization.locales import DEFAULT_LOCALE, LOCALE_COOKIE
from app.schemas.i18n import (
    LocaleInfo,
    LocalePreferenceIn,
    LocalesResponse,
    ResolvedTextOut,
    TextsResponse,
)

router = APIRouter(prefix="/i18n", tags=["i18n"])

NATIVE_NAMES = {"en": "English", "tr": "Türkçe", "zh-CN": "简体中文", "es": "Español"}
MAX_KEYS = 200


@router.get("/locales", response_model=LocalesResponse)
async def locales() -> LocalesResponse:
    return LocalesResponse(
        default=DEFAULT_LOCALE, locales=[LocaleInfo(code=c, native_name=n) for c, n in NATIVE_NAMES.items()]
    )


@router.get("/texts", response_model=TextsResponse)
async def texts(
    db: DbSession,
    locale: LocaleDep,
    keys: Annotated[str, Query(description="comma separated keys", max_length=8000)],
) -> TextsResponse:
    key_list = [k.strip() for k in keys.split(",") if k.strip()]
    if len(key_list) > MAX_KEYS:
        raise ValidationFailedError(f"At most {MAX_KEYS} keys per request", code="too_many_keys")
    resolved = await service.resolve_many(db, key_list, locale)
    return TextsResponse(
        locale=locale,
        texts={k: ResolvedTextOut(value=r.value, locale=r.locale, fallback=r.fallback) for k, r in resolved.items()},
    )


@router.put("/preference", status_code=204)
async def set_preference(body: LocalePreferenceIn, response: Response) -> Response:
    response.set_cookie(
        LOCALE_COOKIE,
        body.locale,
        max_age=60 * 60 * 24 * 365,
        samesite="lax",
        secure=get_settings().is_prod,
        httponly=False,
        path="/",
    )
    response.status_code = 204
    return response
