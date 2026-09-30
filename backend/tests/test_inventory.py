"""Phase 16: inventory, equipment, requirement integrity, overflow mailbox, AFK loot/potions/durability."""

import uuid
from datetime import timedelta

from sqlalchemy import select

from app.db.session import get_sessionmaker
from app.models.character import Character
from app.models.items import ItemInstance
from app.models.progression import EconomyLedger
from app.services import afk, inventory
from tests.test_afk import Clock
from tests.test_classes import _class_id

ADMIN = "/api/v1/admin"


def _key() -> str:
    return f"k-{uuid.uuid4().hex}"


async def _hero(make_client, make_character, level=150, cls="warrior", profile="physical_dps"):  # type: ignore[no-untyped-def]
    staff = await make_client("admin")
    u = await make_client()
    cid = await make_character(u.user_id, level=level, unspent=(level - 1) * 3, base_class_id=await _class_id(cls))
    prog = (await u.http.get(f"/api/v1/characters/{cid}/progression")).json()
    r = await u.http.post(
        f"/api/v1/characters/{cid}/stats/auto",
        json={"profile_code": profile, "expected_version": prog["version"]},
        headers={"Idempotency-Key": _key()},
    )
    assert r.status_code == 200, r.text
    return staff, u, cid


async def _grant(staff, cid, code, qty=1):  # type: ignore[no-untyped-def]
    r = await staff.http.post(
        f"{ADMIN}/characters/{cid}/items",
        json={"template_code": code, "quantity": qty, "reason": "t", "seed": 1},
        headers={"Idempotency-Key": _key()},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _publish(gd, code, data):  # type: ignore[no-untyped-def]
    r = await gd.http.post(f"{ADMIN}/content/item_template", json={"code": code, "data": data})
    assert r.status_code == 201, r.text
    p = await gd.http.post(
        f"{ADMIN}/content/releases",
        json={"items": [{"entity_type": "item_template", "code": code}], "acknowledge_warnings": True},
    )
    assert p.status_code == 200, p.text


def _weapon(**over):  # type: ignore[no-untyped-def]
    base = {
        "category": "weapon",
        "slot": "main_hand",
        "weapon_family": "sword",
        "tier": 0,
        "min_level": 10,
        "rarity": "common",
        "durability": {"max": 40},
        "affix_rules": {"pool": [], "max": 0},
        "base_stats": [{"stat": "attack_power", "amount": 20}],
    }
    return {**base, **over}


async def _equip(u, cid, iid, slot=None):  # type: ignore[no-untyped-def]
    return await u.http.post(
        f"/api/v1/characters/{cid}/equipment/equip", json={"instance_id": iid, **({"slot": slot} if slot else {})}
    )


async def test_equip_updates_single_source_stats_and_unequip(make_client, make_character) -> None:  # type: ignore[no-untyped-def]
    staff, u, cid = await _hero(make_client, make_character)
    axe = await _grant(staff, cid, "militia_axe")
    before = (await u.http.get(f"/api/v1/characters/{cid}/equipment")).json()
    preview = (await u.http.get(f"/api/v1/characters/{cid}/items/{axe}/equip-preview")).json()
    assert preview["equippable"] and preview["slot"] == "main_hand" and preview["deltas"]["attack_power"] > 0
    r = await _equip(u, cid, axe)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["slot"] == "main_hand"
    gained = out["derived"]["attack_power"] - before["derived"]["attack_power"]
    assert abs(gained - preview["deltas"]["attack_power"]) < 1e-6  # preview == live calculator
    prog = (await u.http.get(f"/api/v1/characters/{cid}/progression")).json()
    assert abs(prog["stats"]["derived"]["attack_power"]["final"] - out["derived"]["attack_power"]) < 1e-3
    un = await u.http.post(f"/api/v1/characters/{cid}/equipment/unequip", json={"slot": "main_hand"})
    assert un.status_code == 200 and un.json()["derived"]["attack_power"] == before["derived"]["attack_power"]
    assert (
        await u.http.post(f"/api/v1/characters/{cid}/equipment/unequip", json={"slot": "main_hand"})
    ).status_code == 404
    other = await make_client()
    assert (await _equip(other, cid, axe)).status_code == 404


async def test_requirements_use_gear_free_stats_no_circular_exploit(make_client, make_character) -> None:  # type: ignore[no-untyped-def]
    staff, u, cid = await _hero(make_client, make_character, level=40)
    async with get_sessionmaker()() as db:
        ch = await db.get(Character, cid)
        assert ch is not None
        str_now = int((await inventory.gear_free_primary_stats(db, ch))["STR"])
    gd = await make_client("game_designer")
    booster, needy = f"boost_{uuid.uuid4().hex[:6]}", f"needy_{uuid.uuid4().hex[:6]}"
    await _publish(
        gd,
        booster,
        {
            **_weapon(
                slot="off_hand",
                category="armor",
                weapon_family=None,
                armor_family="shield",
                base_stats=[{"stat": "STR", "amount": 40}],
            )
        },
    )
    await _publish(
        gd,
        needy,
        _weapon(
            min_level=40, requirements={"stats": {"STR": str_now + 10}}, base_stats=[{"stat": "STR", "amount": 50}]
        ),
    )
    n = await _grant(staff, cid, needy)
    r = await _equip(u, cid, n)
    assert r.status_code == 422 and r.json()["error"]["code"] == "requirements_not_met"  # its own +50 STR doesn't count
    b = await _grant(staff, cid, booster)
    assert (await _equip(u, cid, b)).status_code == 200
    r2 = await _equip(u, cid, n)
    assert r2.status_code == 422  # another item's STR doesn't count either (no chains)
    assert any(x["kind"] == "stat" for x in r2.json()["error"]["details"])


async def test_proficiency_slots_two_handed_rings_and_binding(make_client, make_character) -> None:  # type: ignore[no-untyped-def]
    staff, u, cid = await _hero(make_client, make_character, level=60)
    gd = await make_client("game_designer")
    great, shield, ring, wand = (f"{p}_{uuid.uuid4().hex[:6]}" for p in ("gs", "sh", "rg", "wd"))
    await _publish(gd, great, _weapon(weapon_family="greatsword", bind_policy="on_equip"))
    await _publish(
        gd,
        shield,
        _weapon(
            category="armor",
            slot="off_hand",
            weapon_family=None,
            armor_family="shield",
            base_stats=[{"stat": "armor", "amount": 30}],
        ),
    )
    await _publish(
        gd,
        ring,
        {
            "category": "accessory",
            "slot": "ring",
            "tier": 0,
            "min_level": 1,
            "rarity": "common",
            "affix_rules": {"pool": [], "max": 0},
            "base_stats": [{"stat": "LUK", "amount": 1}],
        },
    )
    await _publish(gd, wand, _weapon(weapon_family="wand"))
    w = await _grant(staff, cid, wand)
    r = await _equip(u, cid, w)
    assert r.status_code == 422 and r.json()["error"]["details"][0]["kind"] == "weapon_proficiency"
    s = await _grant(staff, cid, shield)
    assert (await _equip(u, cid, s)).json()["slot"] == "off_hand"
    assert (await _equip(u, cid, s)).status_code == 409  # already equipped
    g = await _grant(staff, cid, great)
    eq = (await _equip(u, cid, g)).json()
    assert eq["slot"] == "main_hand" and eq["displaced"] == [s]  # 2H pushes the shield back to the bag
    blocked = await _equip(u, cid, s)
    assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "two_handed_blocks_off_hand"
    detail = (await u.http.get(f"/api/v1/characters/{cid}/items/{g}")).json()
    assert detail["bound"] is True
    r1, r2 = await _grant(staff, cid, ring), await _grant(staff, cid, ring)
    assert (await _equip(u, cid, r1)).json()["slot"] == "ring_1"
    assert (await _equip(u, cid, r2)).json()["slot"] == "ring_2"
    assert (await _equip(u, cid, w, slot="head")).status_code == 422


async def test_overflow_goes_to_mailbox_then_autosell_never_lost(make_client, make_character, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    real = inventory.config

    async def small(db):  # type: ignore[no-untyped-def]
        return (await real(db)).model_copy(update={"base_capacity": 2, "mailbox_capacity": 1})

    monkeypatch.setattr(inventory, "config", small)
    _, u, cid = await _hero(make_client, make_character, level=20)
    async with get_sessionmaker()() as db:
        ch = await db.get(Character, cid)
        assert ch is not None
        out = await inventory.add_item(
            db, character=ch, template_code="copper_ring", quantity=4, source_type="test", source_id=None, key="ovf1"
        )
        again = await inventory.add_item(
            db, character=ch, template_code="copper_ring", quantity=4, source_type="test", source_id=None, key="ovf1"
        )
        stacks = await inventory.add_item(
            db, character=ch, template_code="copper_ore", quantity=1200, source_type="test", source_id=None, key="ore1"
        )
        await db.commit()
    assert [o["placed"] for o in out] == ["inventory", "inventory", "mail", "sold"]
    assert [o.get("instance_id") for o in again[:3]] == [o.get("instance_id") for o in out[:3]]  # idempotent replay
    assert stacks[0]["placed"] == "sold"  # bag + mailbox full → ore sold, not lost
    async with get_sessionmaker()() as db:
        sells = (
            (
                await db.execute(
                    select(EconomyLedger).where(
                        EconomyLedger.character_id == cid, EconomyLedger.reason == "overflow_autosell"
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(sells) == 3 and all(s.delta > 0 for s in sells)  # ring overflow + two ore stacks; replay added none
    inv = (await u.http.get(f"/api/v1/characters/{cid}/inventory")).json()
    assert inv["used"] == 2 and inv["capacity"] == 2 and inv["mailbox"] == 1 and inv["mailbox_warn"]
    first = inv["items"][0]["id"]
    assert (await u.http.delete(f"/api/v1/characters/{cid}/items/{first}")).status_code == 204
    moved = (await u.http.post(f"/api/v1/characters/{cid}/mailbox/claim")).json()
    assert moved == {"moved": 1, "remaining": 0}


async def test_stackables_merge_up_to_stack_size(make_client, make_character) -> None:  # type: ignore[no-untyped-def]
    _, _, cid = await _hero(make_client, make_character, level=20)
    async with get_sessionmaker()() as db:
        ch = await db.get(Character, cid)
        assert ch is not None
        await inventory.add_item(
            db, character=ch, template_code="copper_ore", quantity=900, source_type="t", source_id=None, key="m1"
        )
        await inventory.add_item(
            db, character=ch, template_code="copper_ore", quantity=300, source_type="t", source_id=None, key="m2"
        )
        await db.commit()
        rows = (
            (
                await db.execute(
                    select(ItemInstance.quantity)
                    .where(ItemInstance.owner_character_id == cid)
                    .order_by(ItemInstance.id)
                )
            )
            .scalars()
            .all()
        )
    assert rows == [999, 201]


async def test_afk_claim_grants_loot_consumes_potions_and_applies_filter(
    make_client, make_character, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    clock = Clock()
    monkeypatch.setattr(afk, "now_utc", clock)
    staff, u, cid = await _hero(make_client, make_character, level=30)
    await _grant(staff, cid, "minor_healing_potion", qty=10)
    prof = (await u.http.get(f"/api/v1/characters/{cid}/afk-profile")).json()["profile"]
    await u.http.put(
        f"/api/v1/characters/{cid}/afk-profile",
        json={"expected_version": prof["version"], "loot_filter": {"min_rarity": "fine", "keep_materials": True}},
    )
    s = await u.http.post(
        f"/api/v1/characters/{cid}/afk/start",
        json={"zone_code": "whispering_meadows", "duration_s": 10800},
        headers={"Idempotency-Key": _key()},
    )
    assert s.status_code == 201, s.text
    clock.now += timedelta(hours=3, seconds=1)
    claim = (await u.http.post(f"/api/v1/characters/{cid}/afk/claim", headers={"Idempotency-Key": _key()})).json()
    res = claim["result"]
    assert claim["loot_pending"] == [] and res["drops"]
    granted = claim["loot_granted"]
    assert granted and any(
        g["placed"] == "sold" and g.get("reason") == "loot_filter" for g in granted
    )  # T0 commons filtered
    inv = (await u.http.get(f"/api/v1/characters/{cid}/inventory")).json()
    potions = sum(i["quantity"] for i in inv["items"] if i["template_code"] == "minor_healing_potion")
    assert potions == 10 - res["potions_used"]
    async with get_sessionmaker()() as db:
        sold = (
            (
                await db.execute(
                    select(EconomyLedger).where(
                        EconomyLedger.character_id == cid, EconomyLedger.reason == "loot_filter_sell"
                    )
                )
            )
            .scalars()
            .all()
        )
        assert sold


async def test_durability_loss_is_idempotent(make_client, make_character) -> None:  # type: ignore[no-untyped-def]
    staff, u, cid = await _hero(make_client, make_character, level=60)
    axe = await _grant(staff, cid, "militia_axe")
    await _equip(u, cid, axe)
    async with get_sessionmaker()() as db:
        ch = await db.get(Character, cid)
        assert ch is not None
        await inventory.apply_durability_loss(db, ch, 10, "afk:test:durability")
        await inventory.apply_durability_loss(db, ch, 10, "afk:test:durability")
        await db.commit()
    d = (await u.http.get(f"/api/v1/characters/{cid}/items/{axe}")).json()
    assert d["durability"] == d["durability_max"] - 6
