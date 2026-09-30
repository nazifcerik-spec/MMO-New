from zoneinfo import available_timezones

from fastapi import APIRouter, Request, Response
from sqlalchemy import select

from app.api.deps import Auth, DbSession, LocaleDep, client_ip
from app.core import rate_limit
from app.core.config import get_settings
from app.core.errors import ValidationFailedError
from app.localization.locales import LOCALE_COOKIE
from app.models.auth import UserSettings
from app.schemas.auth import LoginIn, MeOut, RegisterIn, SettingsIn, SettingsOut
from app.services import audit
from app.services import auth as auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_session_cookies(response: Response, issued: auth_service.IssuedSession) -> None:
    s = get_settings()
    max_age = s.session_ttl_days * 86400
    response.set_cookie(
        s.session_cookie, issued.token, max_age=max_age, httponly=True, secure=s.is_prod, samesite="lax", path="/"
    )
    # Readable by JS for the double-submit header; bound to the session server-side via its hash.
    response.set_cookie(
        s.csrf_cookie, issued.csrf_token, max_age=max_age, httponly=False, secure=s.is_prod, samesite="lax", path="/"
    )


def _clear_cookies(response: Response) -> None:
    s = get_settings()
    response.delete_cookie(s.session_cookie, path="/")
    response.delete_cookie(s.csrf_cookie, path="/")


async def _me(ctx: auth_service.AuthContext) -> MeOut:
    return MeOut(
        id=ctx.user_id,
        email=ctx.email,
        roles=ctx.roles,
        permissions=sorted(ctx.permissions),
        is_staff=ctx.is_staff,
        locale=ctx.locale,
    )


@router.post("/register", response_model=MeOut, status_code=201)
async def register(body: RegisterIn, request: Request, response: Response, db: DbSession) -> MeOut:
    ip = client_ip(request)
    await rate_limit.hit(f"register:ip:{ip}", get_settings().rl_register_ip)
    user = await auth_service.register(db, email=body.email, password=body.password, locale=body.locale, ip=ip)
    issued = await auth_service.issue_session(db, user.id, ip=ip, user_agent=request.headers.get("user-agent"))
    await db.commit()
    _set_session_cookies(response, issued)
    ctx = await auth_service.resolve_session(db, issued.token)
    assert ctx is not None
    return await _me(ctx)


@router.post("/login", response_model=MeOut)
async def login(body: LoginIn, request: Request, response: Response, db: DbSession) -> MeOut:
    issued = await auth_service.login(
        db,
        email=body.email,
        password=body.password,
        ip=client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    await audit.record(
        db,
        actor_id=issued.user_id,
        action="user.login",
        entity_type="user",
        entity_id=issued.user_id,
        ip=client_ip(request),
    )
    await db.commit()
    _set_session_cookies(response, issued)
    ctx = await auth_service.resolve_session(db, issued.token)
    assert ctx is not None
    response.set_cookie(LOCALE_COOKIE, ctx.locale, max_age=31536000, samesite="lax", secure=get_settings().is_prod)
    return await _me(ctx)


@router.post("/logout", status_code=204)
async def logout(ctx: Auth, db: DbSession, response: Response) -> Response:
    await auth_service.logout(db, ctx.session_id)
    await db.commit()
    _clear_cookies(response)
    response.status_code = 204
    return response


@router.get("/me", response_model=MeOut)
async def me(ctx: Auth) -> MeOut:
    return await _me(ctx)


@router.get("/me/settings", response_model=SettingsOut)
async def get_my_settings(ctx: Auth, db: DbSession) -> UserSettings:
    return (await db.execute(select(UserSettings).where(UserSettings.user_id == ctx.user_id))).scalar_one()


@router.put("/me/settings", response_model=SettingsOut)
async def update_my_settings(
    body: SettingsIn, ctx: Auth, db: DbSession, response: Response, _locale: LocaleDep
) -> UserSettings:
    row = (
        await db.execute(select(UserSettings).where(UserSettings.user_id == ctx.user_id).with_for_update())
    ).scalar_one()
    if body.timezone is not None and body.timezone not in available_timezones():
        raise ValidationFailedError("Unknown timezone", code="invalid_timezone")
    for field in ("locale", "timezone", "reduced_motion", "compact_log"):
        value = getattr(body, field)
        if value is not None:
            setattr(row, field, value)
    await db.commit()
    response.set_cookie(LOCALE_COOKIE, row.locale, max_age=31536000, samesite="lax", secure=get_settings().is_prod)
    return row
