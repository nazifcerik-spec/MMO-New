"""Phase 20: ledgered economy — vendor, repair, buyout market (escrow, tax, expiry, exploits), admin dashboard."""

import asyncio
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app.content.loader import load_yaml
from app.db.session import get_sessionmaker
from app.game_engine import economy as rules
from app.models.items import ItemInstance
from app.models.progression import EconomyLedger, MarketListing
from app.services import economy, wallet
from tests.test_afk import Clock
from tests.test_inventory import _grant

CFG = rules.EconomyConfig.model_validate(load_yaml("balance/economy.yaml")["data"])
M = "/api/v1/characters"


def _key() -> str:
    return f"k-{uuid.uuid4().hex}"


@pytest.fixture
def eclock(monkeypatch):  # type: ignore[no-untyped-def]
    c = Clock()
    monkeypatch.setattr(economy, "now_utc", c)
    return c


async def _gold(cid: int, delta: int = 0) -> int:
    async with get_sessionmaker()() as db:
        if delta:
            await wallet.change_gold(db, character_id=cid, delta=delta, reason="admin_grant", idempotency_key=_key())
            await db.commit()
        return (await wallet.get_wallet(db, cid)).gold


async def _trader(make_client, make_character, gold: int = 0):  # type: ignore[no-untyped-def]
    u = await make_client()
    cid = await make_character(u.user_id, level=60)
    if gold:
        await _gold(cid, gold)
    return u, cid


async def _list(u, cid, iid, price, duration=24, key=None):  # type: ignore[no-untyped-def]
    return await u.http.post(
        f"{M}/{cid}/market/listings",
        json={"instance_id": iid, "unit_price": price, "duration_h": duration},
        headers={"Idempotency-Key": key or _key()},
    )


async def _buy(u, cid, lid, key=None):  # type: ignore[no-untyped-def]
    return await u.http.post(f"{M}/{cid}/market/listings/{lid}/buy", headers={"Idempotency-Key": key or _key()})


def test_price_rules_reject_overflow_and_negatives() -> None:
    assert rules.total_price(CFG, 10, 3) == 30
    for bad in ((0, 1), (-5, 1), (10, 0), (CFG.market.max_total_price, 2)):
        with pytest.raises(ValueError):
            rules.total_price(CFG, *bad)
    assert rules.market_tax(CFG, 1000) == 50 and rules.listing_fee(CFG, 10) == 1
    assert rules.vendor_sell_price(CFG, 40, 2) == 20 and rules.vendor_buy_price(CFG, 40, 1) == 160
    assert rules.classify(CFG, "repair", -5) == "sink" and rules.classify(CFG, "afk_reward", 5) == "source"


async def test_vendor_buy_sell_is_ledgered_and_idempotent(make_client, make_character) -> None:  # type: ignore[no-untyped-def]
    staff = await make_client("admin")
    u, cid = await _trader(make_client, make_character, gold=1000)
    stock = (await u.http.get("/api/v1/vendor")).json()["items"]
    potion = next(i for i in stock if i["template_code"] == "minor_healing_potion")
    key = _key()
    r = await u.http.post(
        f"{M}/{cid}/vendor/buy",
        json={"template_code": "minor_healing_potion", "quantity": 3},
        headers={"Idempotency-Key": key},
    )
    assert r.status_code == 200, r.text
    again = await u.http.post(
        f"{M}/{cid}/vendor/buy",
        json={"template_code": "minor_healing_potion", "quantity": 3},
        headers={"Idempotency-Key": key},
    )
    assert again.status_code == 200 and await _gold(cid) == 1000 - 3 * potion["price"]
    not_stock = await u.http.post(
        f"{M}/{cid}/vendor/buy",
        json={"template_code": "militia_axe", "quantity": 1},
        headers={"Idempotency-Key": _key()},
    )
    assert not_stock.json()["error"]["code"] == "not_in_stock"
    axe = await _grant(staff, cid, "militia_axe")
    before = await _gold(cid)
    sk = _key()
    sold = await u.http.post(
        f"{M}/{cid}/vendor/sell", json={"instance_id": axe, "quantity": 1}, headers={"Idempotency-Key": sk}
    )
    assert sold.status_code == 200 and sold.json()["gold"] == 40 * CFG.vendor.sell_price_pct // 100
    assert (
        await u.http.post(
            f"{M}/{cid}/vendor/sell", json={"instance_id": axe, "quantity": 1}, headers={"Idempotency-Key": sk}
        )
    ).json()["replayed"]
    assert await _gold(cid) == before + sold.json()["gold"]
    poor = await _trader(make_client, make_character)
    broke = await poor[0].http.post(
        f"{M}/{poor[1]}/vendor/buy",
        json={"template_code": "minor_healing_potion", "quantity": 1},
        headers={"Idempotency-Key": _key()},
    )
    assert broke.json()["error"]["code"] == "insufficient_funds"


async def test_repair_costs_gold_and_restores_durability(make_client, make_character) -> None:  # type: ignore[no-untyped-def]
    staff = await make_client("admin")
    u, cid = await _trader(make_client, make_character, gold=500)
    axe = await _grant(staff, cid, "militia_axe")
    async with get_sessionmaker()() as db:
        inst = await db.get(ItemInstance, axe)
        assert inst is not None
        inst.durability = inst.durability_max - 10
        await db.commit()
    quote = (await u.http.get(f"{M}/{cid}/repair")).json()
    assert quote["total"] == rules.repair_cost(CFG, 10, 1, None) and quote["items"][0]["missing"] == 10
    key = _key()
    r = await u.http.post(f"{M}/{cid}/repair", json={}, headers={"Idempotency-Key": key})
    assert r.status_code == 200 and r.json()["cost"] == quote["total"]
    assert (await u.http.post(f"{M}/{cid}/repair", json={}, headers={"Idempotency-Key": key})).json()["replayed"]
    assert await _gold(cid) == 500 - quote["total"]
    assert (await u.http.get(f"{M}/{cid}/repair")).json()["total"] == 0


async def test_market_listing_validation_and_exploit_guards(make_client, make_character) -> None:  # type: ignore[no-untyped-def]
    staff = await make_client("admin")
    u, cid = await _trader(make_client, make_character, gold=100)
    axe = await _grant(staff, cid, "militia_axe")
    assert (await _list(u, cid, axe, 0)).status_code == 422
    assert (await _list(u, cid, axe, -10)).status_code == 422
    assert (await _list(u, cid, axe, 10**16)).status_code == 422
    assert (await _list(u, cid, axe, 50, duration=5)).json()["error"]["code"] == "invalid_duration"
    ore = await _grant(staff, cid, "copper_ore", 999)
    over = await _list(u, cid, ore, CFG.market.max_total_price // 500)
    assert over.json()["error"]["code"] == "invalid_price"  # unit × qty overflow
    key = _key()
    ok = await _list(u, cid, axe, 50, key=key)
    assert ok.status_code == 201, ok.text
    assert (await _list(u, cid, axe, 50, key=key)).json()["replayed"]  # idempotent
    dup = await _list(u, cid, axe, 60)
    assert dup.status_code == 409  # escrowed: no double listing / duplication
    eq = await u.http.post(f"{M}/{cid}/equipment/equip", json={"instance_id": axe})
    assert eq.status_code in (404, 409)  # cannot equip an escrowed item
    quest = await _grant(staff, cid, "worn_training_sword")
    async with get_sessionmaker()() as db:
        inst = await db.get(ItemInstance, quest)
        assert inst is not None
        inst.bound = True
        await db.commit()
    assert (await _list(u, cid, quest, 5)).json()["error"]["code"] == "not_tradeable"
    async with get_sessionmaker()() as db:
        fees = (
            await db.execute(
                select(func.count())
                .select_from(EconomyLedger)
                .where(EconomyLedger.character_id == cid, EconomyLedger.reason == "market_fee")
            )
        ).scalar_one()
    assert fees == 1


async def test_market_purchase_is_atomic_taxed_and_idempotent(make_client, make_character) -> None:  # type: ignore[no-untyped-def]
    staff = await make_client("admin")
    seller, sid = await _trader(make_client, make_character, gold=100)
    buyer, bid = await _trader(make_client, make_character, gold=1000)
    axe = await _grant(staff, sid, "militia_axe")
    lid = (await _list(seller, sid, axe, 400)).json()["id"]
    assert (await _buy(seller, sid, lid)).json()["error"]["code"] == "own_listing"
    key = _key()
    r = await _buy(buyer, bid, lid, key)
    assert r.status_code == 200, r.text
    assert r.json()["tax"] == 20 and r.json()["total"] == 400
    assert (await _buy(buyer, bid, lid, key)).json()["replayed"]
    assert await _gold(bid) == 600
    assert await _gold(sid) == 100 - 4 + 400 - 20  # fee 1% + proceeds - 5% tax
    third, tid = await _trader(make_client, make_character, gold=1000)
    assert (await _buy(third, tid, lid)).json()["error"]["code"] == "listing_unavailable"
    async with get_sessionmaker()() as db:
        inst = await db.get(ItemInstance, axe)
        assert inst is not None and inst.owner_character_id == bid and inst.location == "inventory"


async def test_concurrent_buyers_only_one_wins(make_client, make_character) -> None:  # type: ignore[no-untyped-def]
    staff = await make_client("admin")
    seller, sid = await _trader(make_client, make_character)
    buyers = [await _trader(make_client, make_character, gold=1000) for _ in range(4)]
    axe = await _grant(staff, sid, "militia_axe")
    async with get_sessionmaker()() as db:
        await wallet.change_gold(db, character_id=sid, delta=10, reason="admin_grant", idempotency_key=_key())
        await db.commit()
    lid = (await _list(seller, sid, axe, 300)).json()["id"]
    results = await asyncio.gather(*(_buy(u, c, lid) for u, c in buyers))
    codes = sorted(r.status_code for r in results)
    assert codes == [200, 409, 409, 409], [r.text for r in results]
    golds = [await _gold(c) for _, c in buyers]
    assert sorted(golds) == [700, 1000, 1000, 1000]  # no double charge, no double item


async def test_cancel_and_expiry_return_items(make_client, make_character, eclock) -> None:  # type: ignore[no-untyped-def]
    staff = await make_client("admin")
    u, cid = await _trader(make_client, make_character, gold=100)
    a = await _grant(staff, cid, "militia_axe")
    b = await _grant(staff, cid, "militia_axe")
    la = (await _list(u, cid, a, 50)).json()["id"]
    lb = (await _list(u, cid, b, 50, duration=12)).json()["id"]
    other, oid = await _trader(make_client, make_character, gold=100)
    assert (await other.http.post(f"{M}/{oid}/market/listings/{la}/cancel")).status_code == 404
    c = await u.http.post(f"{M}/{cid}/market/listings/{la}/cancel")
    assert c.status_code == 200 and c.json()["status"] == "cancelled"
    eclock.now += timedelta(hours=13)
    assert (await _buy(other, oid, lb)).json()["error"]["code"] == "listing_expired"
    async with get_sessionmaker()() as db:
        assert await economy.expire_due(db, now=eclock.now) >= 1
        await db.commit()
        rows = {
            r.id: r.status
            for r in (await db.execute(select(MarketListing).where(MarketListing.id.in_([la, lb])))).scalars()
        }
        locs = {
            i.id: i.location
            for i in (await db.execute(select(ItemInstance).where(ItemInstance.id.in_([a, b])))).scalars()
        }
    assert rows == {la: "cancelled", lb: "expired"} and set(locs.values()) == {"inventory"}


async def test_market_browse_paginates_by_price(make_client, make_character) -> None:  # type: ignore[no-untyped-def]
    staff = await make_client("admin")
    u, cid = await _trader(make_client, make_character, gold=1000)
    for p in (30, 10, 20):
        iid = await _grant(staff, cid, "iron_ingot", 1)
        assert (await _list(u, cid, iid, p)).status_code == 201
    page = (await u.http.get("/api/v1/market", params={"template_code": "iron_ingot", "max_unit_price": 35})).json()
    prices = [i["unit_price"] for i in page["items"]]
    assert prices == sorted(prices) and {10, 20, 30} <= set(prices)
    assert all(i["status"] == "active" for i in page["items"])


async def test_economy_dashboard_aggregates_and_requires_permission(make_client, make_character) -> None:  # type: ignore[no-untyped-def]
    player = await make_client()
    assert (await player.http.get("/api/v1/admin/economy/summary")).status_code == 403
    gd = await make_client("game_designer")
    r = await gd.http.get("/api/v1/admin/economy/summary", params={"days": 1})
    assert r.status_code == 200, r.text
    body = r.json()
    kinds = {x["reason"]: x["kind"] for x in body["gold"]["by_reason"]}
    assert kinds.get("market_tax") == "sink" and kinds.get("admin_grant") == "source"
    assert body["market"]["sales"] >= 1 and body["market"]["tax"] >= 1 and "traded" in body["items"]
    assert (await gd.http.get("/api/v1/admin/economy/summary", params={"days": 365})).status_code == 422


async def test_admin_gold_grant_is_permissioned_audited_and_idempotent(make_client, make_character) -> None:  # type: ignore[no-untyped-def]
    _, cid = await _trader(make_client, make_character)
    url = f"/api/v1/admin/characters/{cid}/gold"
    gd = await make_client("game_designer")  # economy.view only
    assert (
        await gd.http.post(url, json={"amount": 50, "reason": "t"}, headers={"Idempotency-Key": _key()})
    ).status_code == 403
    admin = await make_client("admin")
    key = _key()
    r = await admin.http.post(url, json={"amount": 50, "reason": "compensation"}, headers={"Idempotency-Key": key})
    assert r.status_code == 200 and r.json()["balance_after"] == 50
    assert (await admin.http.post(url, json={"amount": 50, "reason": "x"}, headers={"Idempotency-Key": key})).json()[
        "replayed"
    ]
    assert await _gold(cid) == 50
    neg = await admin.http.post(url, json={"amount": -500, "reason": "t"}, headers={"Idempotency-Key": _key()})
    assert neg.json()["error"]["code"] == "insufficient_funds"
