from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Query
from pydantic import Field

from app.api.deps import Auth, DbSession, IdempotencyKey, LocaleDep, require
from app.core import rate_limit
from app.core.config import get_settings
from app.schemas.common import ApiModel
from app.services import characters, economy
from app.services.auth import AuthContext

router = APIRouter(tags=["economy"])
CODE = r"^[a-z0-9_]+$"
MAX_PRICE = 10**15


async def _limit(user_id: int) -> None:
    await rate_limit.hit(f"econ:{user_id}", get_settings().rl_mutation_user)


# --------------------------------------------------------------------------- vendor / repair
@router.get("/vendor")
async def vendor_stock(
    db: DbSession, locale: LocaleDep, after: str | None = Query(default=None, max_length=96, pattern=CODE)
) -> dict[str, Any]:
    return await economy.vendor_stock(db, locale, after=after)


class VendorBuyIn(ApiModel):
    template_code: str = Field(max_length=96, pattern=CODE)
    quantity: int = Field(ge=1, le=100_000)


@router.post("/characters/{character_id}/vendor/buy")
async def vendor_buy(
    character_id: int, body: VendorBuyIn, ctx: Auth, db: DbSession, key: IdempotencyKey
) -> dict[str, Any]:
    await _limit(ctx.user_id)
    ch = await characters.get_owned(db, ctx.user_id, character_id, for_update=True)
    out = await economy.vendor_buy(db, character=ch, template_code=body.template_code, quantity=body.quantity, key=key)
    await db.commit()
    return out


class VendorSellIn(ApiModel):
    instance_id: int
    quantity: int = Field(ge=1, le=100_000)


@router.post("/characters/{character_id}/vendor/sell")
async def vendor_sell(
    character_id: int, body: VendorSellIn, ctx: Auth, db: DbSession, key: IdempotencyKey
) -> dict[str, Any]:
    await _limit(ctx.user_id)
    ch = await characters.get_owned(db, ctx.user_id, character_id, for_update=True)
    out = await economy.vendor_sell(db, character=ch, instance_id=body.instance_id, quantity=body.quantity, key=key)
    await db.commit()
    return out


@router.get("/characters/{character_id}/repair")
async def repair_quote(character_id: int, ctx: Auth, db: DbSession) -> dict[str, Any]:
    ch = await characters.get_owned(db, ctx.user_id, character_id)
    return await economy.repair_quote(db, ch)


class RepairIn(ApiModel):
    instance_id: int | None = None


@router.post("/characters/{character_id}/repair")
async def repair(character_id: int, body: RepairIn, ctx: Auth, db: DbSession, key: IdempotencyKey) -> dict[str, Any]:
    await _limit(ctx.user_id)
    ch = await characters.get_owned(db, ctx.user_id, character_id, for_update=True)
    out = await economy.repair(db, character=ch, instance_id=body.instance_id, key=key)
    await db.commit()
    return out


# --------------------------------------------------------------------------- market
@router.get("/market")
async def browse(
    db: DbSession,
    locale: LocaleDep,
    template_code: str | None = Query(default=None, max_length=96, pattern=CODE),
    category: str | None = Query(default=None, max_length=32, pattern=CODE),
    tier: int | None = Query(default=None, ge=0, le=10),
    rarity: str | None = Query(default=None, max_length=16, pattern=CODE),
    max_unit_price: int | None = Query(default=None, ge=1, le=MAX_PRICE),
    after_price: int | None = Query(default=None, ge=0, le=MAX_PRICE),
    after_id: int | None = Query(default=None, ge=0),
) -> dict[str, Any]:
    f = economy.BrowseFilters(
        template_code=template_code, category=category, tier=tier, rarity=rarity, max_unit_price=max_unit_price,
        after_price=after_price, after_id=after_id,
    )  # fmt: skip
    return await economy.browse(db, f, locale)


@router.get("/characters/{character_id}/market/listings")
async def my_listings(character_id: int, ctx: Auth, db: DbSession, locale: LocaleDep) -> list[dict[str, Any]]:
    ch = await characters.get_owned(db, ctx.user_id, character_id)
    return await economy.my_listings(db, ch, locale)


class ListingIn(ApiModel):
    instance_id: int
    unit_price: int = Field(ge=1, le=MAX_PRICE)
    duration_h: int = Field(ge=1, le=720)


@router.post("/characters/{character_id}/market/listings", status_code=201)
async def create_listing(
    character_id: int, body: ListingIn, ctx: Auth, db: DbSession, key: IdempotencyKey
) -> dict[str, Any]:
    await _limit(ctx.user_id)
    ch = await characters.get_owned(db, ctx.user_id, character_id, for_update=True)
    out = await economy.create_listing(
        db, character=ch, instance_id=body.instance_id, unit_price=body.unit_price, duration_h=body.duration_h, key=key
    )
    await db.commit()
    return out


@router.post("/characters/{character_id}/market/listings/{listing_id}/cancel")
async def cancel_listing(character_id: int, listing_id: int, ctx: Auth, db: DbSession) -> dict[str, Any]:
    await _limit(ctx.user_id)
    ch = await characters.get_owned(db, ctx.user_id, character_id, for_update=True)
    out = await economy.cancel_listing(db, character=ch, listing_id=listing_id)
    await db.commit()
    return out


@router.post("/characters/{character_id}/market/listings/{listing_id}/buy")
async def buy(character_id: int, listing_id: int, ctx: Auth, db: DbSession, key: IdempotencyKey) -> dict[str, Any]:
    await _limit(ctx.user_id)
    ch = await characters.get_owned(db, ctx.user_id, character_id, for_update=True)
    out = await economy.buy(db, buyer=ch, listing_id=listing_id, key=key)
    await db.commit()
    return out


# --------------------------------------------------------------------------- admin dashboard
Viewer = Annotated[AuthContext, require("economy.view")]


@router.get("/admin/economy/summary")
async def dashboard(
    db: DbSession,
    _: Viewer,
    days: int = Query(default=7, ge=1, le=90),
) -> dict[str, Any]:
    end = datetime.now(UTC)
    return await economy.dashboard(db, start=end - timedelta(days=days), end=end)


Granter = Annotated[AuthContext, require("economy.grant")]


class GoldGrantIn(ApiModel):
    amount: int = Field(ge=-(10**12), le=10**12)
    reason: str = Field(min_length=1, max_length=200)


@router.post("/admin/characters/{character_id}/gold")
async def grant_gold(
    character_id: int, body: GoldGrantIn, ctx: Granter, db: DbSession, key: IdempotencyKey
) -> dict[str, Any]:
    """Audited admin currency adjustment (ledger reason admin_grant); idempotent on the key."""
    ch = await characters.get_any(db, character_id, for_update=True)
    entry = await economy.admin_grant_gold(
        db, character=ch, amount=body.amount, note=body.reason, actor_id=ctx.user_id, key=key
    )
    await db.commit()
    return entry
