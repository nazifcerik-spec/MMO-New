"""Server-authoritative economy: static vendor prices, repair, buyout market (escrow, atomic purchase) and the
admin economy dashboard. Every gold movement goes through `wallet.change_gold` (ledger + correlation id);
every item movement appends `item_provenance`. All mutating calls are idempotent on a client key."""

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError, ValidationFailedError
from app.game_engine import economy as rules
from app.game_engine.items import RARITY_ORDER
from app.localization.service import resolve_text_map
from app.models.character import Character
from app.models.items import ItemInstance, ItemProvenance, ItemTemplate
from app.models.progression import EconomyLedger, MarketListing
from app.services import audit, events, inventory, items, wallet
from app.services.content.types.balance import get_published_balance

MAX_DASHBOARD_DAYS = 90


def now_utc() -> datetime:
    return datetime.now(UTC)


async def config(db: AsyncSession) -> rules.EconomyConfig:
    return await get_published_balance(db, "economy", rules.EconomyConfig)


async def _provenance(
    db: AsyncSession, inst: ItemInstance, event: str, key: str, character_id: int, details: dict[str, Any]
) -> None:
    db.add(
        ItemProvenance(
            instance_id=inst.id, provenance_id=inst.provenance_id, event=event, character_id=character_id,
            idempotency_key=key, details=details,
        )
    )  # fmt: skip
    await db.flush()


async def _place_owned(db: AsyncSession, character: Character, inst: ItemInstance) -> str:
    """Move an existing instance into the character's bag, or the mailbox when the bag is full (never lost)."""
    used = await inventory._count(db, character.id, "inventory")
    inst.owner_character_id = character.id
    inst.location = "inventory" if used < await inventory.capacity(db, character) else "mail"
    await db.flush()
    return inst.location


async def _template(db: AsyncSession, code: str) -> ItemTemplate:
    return await items.published_template(db, code)


# --------------------------------------------------------------------------- vendor
async def vendor_stock(db: AsyncSession, locale: str, *, after: str | None = None) -> dict[str, Any]:
    cfg = await config(db)
    allowed = RARITY_ORDER[: RARITY_ORDER.index(cfg.vendor.stock_max_rarity) + 1]
    stmt = (
        select(ItemTemplate)
        .where(
            ItemTemplate.status == "published",
            ItemTemplate.deleted_at.is_(None),
            ItemTemplate.sources.contains([{"kind": "vendor"}]),
            ItemTemplate.rarity.in_(allowed),
        )
        .order_by(ItemTemplate.code)
        .limit(cfg.market.page_size + 1)
    )
    if after:
        stmt = stmt.where(ItemTemplate.code > after)
    rows = list((await db.execute(stmt)).scalars())
    more = len(rows) > cfg.market.page_size
    rows = rows[: cfg.market.page_size]
    text = await resolve_text_map(db, [f"item.{t.code}.name" for t in rows], locale)
    return {
        "items": [
            {
                "template_code": t.code,
                "name": text[f"item.{t.code}.name"],
                "category": t.category,
                "tier": t.tier,
                "rarity": t.rarity,
                "min_level": t.min_level,
                "stack_size": t.stack_size,
                "price": rules.vendor_buy_price(cfg, t.vendor_value, 1),
            }
            for t in rows
        ],
        "next_cursor": rows[-1].code if more and rows else None,
    }


async def vendor_buy(
    db: AsyncSession, *, character: Character, template_code: str, quantity: int, key: str
) -> dict[str, Any]:
    cfg = await config(db)
    if not 1 <= quantity <= cfg.vendor.max_quantity:
        raise ValidationFailedError("Invalid quantity", code="invalid_quantity")
    tpl = await _template(db, template_code)
    allowed = RARITY_ORDER[: RARITY_ORDER.index(cfg.vendor.stock_max_rarity) + 1]
    if not any(s.get("kind") == "vendor" for s in tpl.sources) or tpl.rarity not in allowed:
        raise ConflictError("This vendor does not sell that item", code="not_in_stock")
    if tpl.stack_size == 1 and quantity > 20:
        raise ValidationFailedError("Buy at most 20 non-stackable items at once", code="invalid_quantity")
    price = rules.vendor_buy_price(cfg, tpl.vendor_value, quantity)
    entry = await wallet.change_gold(
        db, character_id=character.id, delta=-price, reason="vendor_buy", idempotency_key=f"vendor_buy:{key}",
        ref_type="item_template", ref_id=template_code,
    )  # fmt: skip
    placed = await inventory.add_item(
        db, character=character, template_code=template_code, quantity=quantity, source_type="vendor",
        source_id=template_code, key=f"vendor_buy:{key}",
    )  # fmt: skip
    return {"template_code": template_code, "quantity": quantity, "price": -entry.delta, "placed": placed}


async def vendor_sell(
    db: AsyncSession, *, character: Character, instance_id: int, quantity: int, key: str
) -> dict[str, Any]:
    prior = await wallet.find_entry(db, character.id, f"vendor_sell:{key}")
    if prior is not None:
        return {"gold": prior.delta, "replayed": True}
    cfg = await config(db)
    inst = await items.get_owned_instance(db, character.id, instance_id, for_update=True)
    if inst.location != "inventory":
        raise ConflictError("Only bag items can be sold", code="item_not_in_bag")
    data = await items.revision_data(db, inst.template_code, inst.template_revision_no)
    if not data.get("sellable", True):
        raise ConflictError("This item cannot be sold", code="not_sellable")
    if not 1 <= quantity <= inst.quantity:
        raise ValidationFailedError("Invalid quantity", code="invalid_quantity")
    gold = rules.vendor_sell_price(cfg, int(data.get("vendor_value", 0)), quantity)
    await _provenance(
        db, inst, "sold", f"vendor_sell:{character.id}:{key}", character.id, {"qty": quantity, "gold": gold}
    )
    if quantity == inst.quantity:
        inst.location = "destroyed"
    else:
        inst.quantity -= quantity
    if gold:
        await wallet.change_gold(
            db, character_id=character.id, delta=gold, reason="vendor_sell", idempotency_key=f"vendor_sell:{key}",
            ref_type="item_instance", ref_id=str(inst.id),
        )  # fmt: skip
    await db.flush()
    return {"gold": gold, "replayed": False}


# --------------------------------------------------------------------------- repair
async def repair_quote(db: AsyncSession, character: Character, instance_id: int | None = None) -> dict[str, Any]:
    cfg = await config(db)
    stmt = select(ItemInstance).where(
        ItemInstance.owner_character_id == character.id,
        ItemInstance.location.in_(("inventory", "equipped")),
        ItemInstance.durability_max > 0,
        ItemInstance.durability < ItemInstance.durability_max,
    )
    if instance_id is not None:
        stmt = stmt.where(ItemInstance.id == instance_id)
    rows = list((await db.execute(stmt.order_by(ItemInstance.id))).scalars())
    lines = []
    for inst in rows:
        tpl_tier = (await items.revision_data(db, inst.template_code, inst.template_revision_no))["tier"]
        cost = rules.repair_cost(
            cfg, inst.durability_max - inst.durability, tpl_tier, items.instance_state(inst)["quality"]
        )
        lines.append(
            {
                "instance_id": inst.id,
                "template_code": inst.template_code,
                "missing": inst.durability_max - inst.durability,
                "cost": cost,
            }
        )
    return {"items": lines, "total": sum(line["cost"] for line in lines)}


async def repair(db: AsyncSession, *, character: Character, instance_id: int | None, key: str) -> dict[str, Any]:
    prior = await wallet.find_entry(db, character.id, f"repair:{key}")
    if prior is not None:
        return {"cost": -prior.delta, "repaired": [], "replayed": True}
    quote = await repair_quote(db, character, instance_id)
    if not quote["items"]:
        return {"cost": 0, "repaired": [], "replayed": False}
    if quote["total"]:
        await wallet.change_gold(
            db, character_id=character.id, delta=-quote["total"], reason="repair", idempotency_key=f"repair:{key}",
            ref_type="repair", ref_id=str(instance_id or "all"),
        )  # fmt: skip
    ids = [line["instance_id"] for line in quote["items"]]
    for inst in (await db.execute(select(ItemInstance).where(ItemInstance.id.in_(ids)).with_for_update())).scalars():
        inst.durability = inst.durability_max
    await db.flush()
    return {"cost": quote["total"], "repaired": ids, "replayed": False}


# --------------------------------------------------------------------------- market
def _listing_view(row: MarketListing, names: dict[str, str], now: datetime) -> dict[str, Any]:
    return {
        "id": row.id,
        "template_code": row.template_code,
        "name": names.get(f"item.{row.template_code}.name", row.template_code),
        "category": row.category,
        "tier": row.tier,
        "rarity": row.rarity,
        "quantity": row.quantity,
        "unit_price": row.unit_price,
        "total_price": row.total_price,
        "status": "expired" if row.status == "active" and row.expires_at <= now else row.status,
        "expires_at": row.expires_at.isoformat(),
        "seller_character_id": row.seller_character_id,
        "instance_id": row.instance_id,
    }


async def create_listing(
    db: AsyncSession, *, character: Character, instance_id: int, unit_price: int, duration_h: int, key: str
) -> dict[str, Any]:
    existing = (
        await db.execute(
            select(MarketListing).where(
                MarketListing.seller_character_id == character.id, MarketListing.listing_key == key
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return {**_listing_view(existing, {}, now_utc()), "replayed": True}
    cfg = await config(db)
    if duration_h not in cfg.market.durations_h:
        raise ValidationFailedError(f"Duration must be one of {list(cfg.market.durations_h)}", code="invalid_duration")
    inst = await items.get_owned_instance(db, character.id, instance_id, for_update=True)
    if inst.location != "inventory":
        raise ConflictError("Only unequipped bag items can be listed", code="item_not_in_bag")
    data = await items.revision_data(db, inst.template_code, inst.template_revision_no)
    if inst.bound or not data.get("tradeable", True) or data.get("bind_policy") in ("on_pickup", "account"):
        raise ConflictError("This item cannot be traded", code="not_tradeable")
    try:
        total = rules.total_price(cfg, unit_price, inst.quantity)
    except ValueError as exc:
        raise ValidationFailedError(str(exc), code="invalid_price") from exc
    active = (
        await db.execute(
            select(func.count())
            .select_from(MarketListing)
            .where(MarketListing.seller_character_id == character.id, MarketListing.status == "active")
        )
    ).scalar_one()
    if active >= cfg.market.max_active_listings:
        raise ConflictError("Too many active listings", code="listing_limit")
    fee = rules.listing_fee(cfg, total)
    if fee:
        await wallet.change_gold(
            db, character_id=character.id, delta=-fee, reason="market_fee", idempotency_key=f"market_fee:{key}",
            ref_type="item_instance", ref_id=str(inst.id),
        )  # fmt: skip
    inst.location = "market"
    row = MarketListing(
        seller_character_id=character.id, instance_id=inst.id, template_code=inst.template_code,
        category=data["category"], tier=data["tier"], rarity=data["rarity"], quantity=inst.quantity,
        unit_price=unit_price, total_price=total, tax_pct=cfg.market.tax_pct, fee_paid=fee, status="active",
        listing_key=key, expires_at=now_utc() + timedelta(hours=duration_h),
    )  # fmt: skip
    db.add(row)
    await db.flush()
    await _provenance(db, inst, "listed", f"market_list:{row.id}", character.id, {"listing": row.id, "total": total})
    return {**_listing_view(row, {}, now_utc()), "fee": fee, "replayed": False}


async def _locked_listing(db: AsyncSession, listing_id: int) -> MarketListing:
    row = (
        await db.execute(select(MarketListing).where(MarketListing.id == listing_id).with_for_update())
    ).scalar_one_or_none()
    if row is None:
        raise NotFoundError("Listing not found", code="listing_not_found")
    return row


async def _return_to_seller(db: AsyncSession, row: MarketListing, status: str) -> None:
    seller = await db.get(Character, row.seller_character_id)
    inst = await db.get(ItemInstance, row.instance_id, with_for_update=True)
    if seller is not None and inst is not None:
        where = await _place_owned(db, seller, inst)
        await _provenance(
            db, inst, f"market_{status}", f"market_{status}:{row.id}", seller.id, {"listing": row.id, "to": where}
        )
    row.status, row.closed_at = status, now_utc()
    await db.flush()


async def cancel_listing(db: AsyncSession, *, character: Character, listing_id: int) -> dict[str, Any]:
    row = await _locked_listing(db, listing_id)
    if row.seller_character_id != character.id:
        raise NotFoundError("Listing not found", code="listing_not_found")
    if row.status != "active":
        raise ConflictError("Listing is no longer active", code="listing_unavailable")
    await _return_to_seller(db, row, "cancelled")
    return {"id": row.id, "status": row.status}


async def buy(db: AsyncSession, *, buyer: Character, listing_id: int, key: str) -> dict[str, Any]:
    prior = (
        await db.execute(
            select(MarketListing).where(MarketListing.buyer_character_id == buyer.id, MarketListing.purchase_key == key)
        )
    ).scalar_one_or_none()
    if prior is not None:
        if prior.id != listing_id:
            raise ConflictError("Idempotency key reused for another listing", code="idempotency_conflict")
        return {"listing_id": prior.id, "total": prior.total_price, "replayed": True}
    row = await _locked_listing(db, listing_id)  # serializes concurrent buyers on this listing
    if row.status != "active":
        raise ConflictError("Listing is no longer available", code="listing_unavailable")
    if row.expires_at <= now_utc():
        raise ConflictError("Listing has expired", code="listing_expired")
    seller = await db.get(Character, row.seller_character_id)
    if seller is None:
        raise ConflictError("Listing is no longer available", code="listing_unavailable")
    if seller.id == buyer.id or seller.user_id == buyer.user_id:
        raise ConflictError("You cannot buy your own listing", code="own_listing")
    total = row.total_price
    tax = int(total * row.tax_pct / 100)
    await wallet.change_gold(
        db, character_id=buyer.id, delta=-total, reason="market_purchase", idempotency_key=f"market_buy:{row.id}",
        ref_type="market_listing", ref_id=str(row.id),
    )  # fmt: skip
    await wallet.change_gold(
        db, character_id=seller.id, delta=total, reason="market_proceeds", idempotency_key=f"market_sale:{row.id}",
        ref_type="market_listing", ref_id=str(row.id),
    )  # fmt: skip
    if tax:
        await wallet.change_gold(
            db, character_id=seller.id, delta=-tax, reason="market_tax", idempotency_key=f"market_tax:{row.id}",
            ref_type="market_listing", ref_id=str(row.id),
        )  # fmt: skip
    inst = await db.get(ItemInstance, row.instance_id, with_for_update=True)
    if inst is None or inst.location != "market":
        raise ConflictError("Escrowed item missing", code="listing_unavailable")
    where = await _place_owned(db, buyer, inst)
    await _provenance(
        db, inst, "traded", f"market_buy:{row.id}", buyer.id, {"listing": row.id, "from": seller.id, "total": total}
    )
    row.status, row.buyer_character_id, row.purchase_key, row.closed_at = "sold", buyer.id, key, now_utc()
    await db.flush()
    for who in (buyer, seller):
        await events.emit(db, who, "action", {"action": "trade"})
    await audit.record(
        db, actor_id=buyer.user_id, action="market.buy", entity_type="market_listing", entity_id=row.id,
        meta={"total": total, "tax": tax, "seller": seller.id, "buyer": buyer.id},
    )  # fmt: skip
    return {"listing_id": row.id, "total": total, "tax": tax, "placed": where, "replayed": False}


async def expire_due(db: AsyncSession, *, now: datetime | None = None, limit: int = 500) -> int:
    now = now or now_utc()
    rows = list(
        (
            await db.execute(
                select(MarketListing)
                .where(MarketListing.status == "active", MarketListing.expires_at <= now)
                .order_by(MarketListing.expires_at)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        ).scalars()
    )
    for row in rows:
        await _return_to_seller(db, row, "expired")
    return len(rows)


class BrowseFilters:
    def __init__(
        self, *, template_code: str | None = None, category: str | None = None, tier: int | None = None,
        rarity: str | None = None, max_unit_price: int | None = None, after_price: int | None = None,
        after_id: int | None = None,
    ) -> None:  # fmt: skip
        self.template_code, self.category, self.tier, self.rarity = template_code, category, tier, rarity
        self.max_unit_price, self.after_price, self.after_id = max_unit_price, after_price, after_id


async def browse(db: AsyncSession, f: BrowseFilters, locale: str) -> dict[str, Any]:
    cfg = await config(db)
    now = now_utc()
    stmt = select(MarketListing).where(MarketListing.status == "active", MarketListing.expires_at > now)
    for col, val in (
        (MarketListing.template_code, f.template_code),
        (MarketListing.category, f.category),
        (MarketListing.tier, f.tier),
        (MarketListing.rarity, f.rarity),
    ):
        if val is not None:
            stmt = stmt.where(col == val)
    if f.max_unit_price is not None:
        stmt = stmt.where(MarketListing.unit_price <= f.max_unit_price)
    if f.after_price is not None and f.after_id is not None:
        stmt = stmt.where(
            or_(
                MarketListing.unit_price > f.after_price,
                and_(MarketListing.unit_price == f.after_price, MarketListing.id > f.after_id),
            )
        )
    rows = list(
        (
            await db.execute(stmt.order_by(MarketListing.unit_price, MarketListing.id).limit(cfg.market.page_size + 1))
        ).scalars()
    )
    more = len(rows) > cfg.market.page_size
    rows = rows[: cfg.market.page_size]
    names = await resolve_text_map(db, list({f"item.{r.template_code}.name" for r in rows}), locale)
    return {
        "items": [_listing_view(r, names, now) for r in rows],
        "next_cursor": {"after_price": rows[-1].unit_price, "after_id": rows[-1].id} if more and rows else None,
        "tax_pct": cfg.market.tax_pct,
        "listing_fee_pct": cfg.market.listing_fee_pct,
        "durations_h": list(cfg.market.durations_h),
    }


async def my_listings(db: AsyncSession, character: Character, locale: str) -> list[dict[str, Any]]:
    rows = list(
        (
            await db.execute(
                select(MarketListing)
                .where(MarketListing.seller_character_id == character.id)
                .order_by(MarketListing.id.desc())
                .limit(100)
            )
        ).scalars()
    )
    names = await resolve_text_map(db, list({f"item.{r.template_code}.name" for r in rows}), locale)
    return [_listing_view(r, names, now_utc()) for r in rows]


# --------------------------------------------------------------------------- admin
async def admin_grant_gold(
    db: AsyncSession, *, character: Character, amount: int, note: str, actor_id: int, key: str
) -> dict[str, Any]:
    if amount == 0:
        raise ValidationFailedError("Amount must be non-zero", code="invalid_amount")
    prior = await wallet.find_entry(db, character.id, f"admin_grant:{key}")
    entry = prior or await wallet.change_gold(
        db, character_id=character.id, delta=amount, reason="admin_grant", idempotency_key=f"admin_grant:{key}",
        ref_type="admin", ref_id=str(actor_id),
    )  # fmt: skip
    if prior is None:
        await audit.record(
            db, actor_id=actor_id, action="economy.grant_gold", entity_type="character", entity_id=character.id,
            meta={"amount": amount, "note": note, "balance_after": entry.balance_after},
        )  # fmt: skip
    return {"delta": entry.delta, "balance_after": entry.balance_after, "replayed": prior is not None}


# --------------------------------------------------------------------------- admin dashboard
async def dashboard(db: AsyncSession, *, start: datetime, end: datetime) -> dict[str, Any]:
    if end <= start or end - start > timedelta(days=MAX_DASHBOARD_DAYS):
        raise ValidationFailedError(f"Window must be 1s-{MAX_DASHBOARD_DAYS} days", code="invalid_window")
    cfg = await config(db)
    window = and_(EconomyLedger.created_at >= start, EconomyLedger.created_at < end)
    by_reason = (
        await db.execute(
            select(
                EconomyLedger.reason,
                func.count(),
                func.coalesce(func.sum(case((EconomyLedger.delta > 0, EconomyLedger.delta), else_=0)), 0),
                func.coalesce(func.sum(case((EconomyLedger.delta < 0, -EconomyLedger.delta), else_=0)), 0),
            )
            .where(window, EconomyLedger.currency == "gold")
            .group_by(EconomyLedger.reason)
            .order_by(EconomyLedger.reason)
        )
    ).all()
    reasons = []
    totals = {"source": 0, "sink": 0, "transfer": 0}
    for reason, n, gained, spent in by_reason:
        kind = rules.classify(cfg, reason, int(gained) - int(spent))
        net = int(gained) - int(spent)
        totals[kind] += abs(net) if kind != "transfer" else int(gained)
        reasons.append({"reason": reason, "kind": kind, "entries": n, "gold_in": int(gained), "gold_out": int(spent)})
    events = (
        await db.execute(
            select(ItemProvenance.event, func.count())
            .where(ItemProvenance.created_at >= start, ItemProvenance.created_at < end)
            .group_by(ItemProvenance.event)
            .order_by(ItemProvenance.event)
        )
    ).all()
    market = (
        await db.execute(
            select(
                func.count(),
                func.coalesce(func.sum(MarketListing.total_price), 0),
                func.coalesce(func.sum(func.floor(MarketListing.total_price * MarketListing.tax_pct / 100)), 0),
            ).where(MarketListing.status == "sold", MarketListing.closed_at >= start, MarketListing.closed_at < end)
        )
    ).one()
    active = (
        await db.execute(select(func.count()).select_from(MarketListing).where(MarketListing.status == "active"))
    ).scalar_one()
    return {
        "window": {"start": start.isoformat(), "end": end.isoformat()},
        "gold": {"sources": totals["source"], "sinks": totals["sink"], "transfers": totals["transfer"],
                 "net_created": totals["source"] - totals["sink"], "by_reason": reasons},
        "items": {e: int(n) for e, n in events},
        "market": {"sales": int(market[0]), "volume": int(market[1]), "tax": int(market[2]),
                   "active_listings": int(active)},
    }  # fmt: skip
