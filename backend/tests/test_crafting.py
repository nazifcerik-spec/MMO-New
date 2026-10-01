"""Phase 18: recipes, craft queue (reservation/cancel/idempotent claim), quality, AFK gathering, enchanting, salvage."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.content.loader import load_yaml
from app.db.session import get_sessionmaker
from app.game_engine import afk as afk_engine
from app.game_engine import crafting as engine
from app.models.crafting import EnchantEvent
from app.models.items import ItemInstance
from app.services import crafting, wallet
from tests.test_afk import Clock, _start
from tests.test_afk import _hero as afk_hero
from tests.test_inventory import _grant, _hero

CFG = engine.CraftingConfig.model_validate(load_yaml("balance/crafting.yaml")["data"])


def _key() -> str:
    return f"k-{uuid.uuid4().hex}"


@pytest.fixture
def cclock(monkeypatch):  # type: ignore[no-untyped-def]
    from app.services import afk

    c = Clock()
    monkeypatch.setattr(crafting, "now_utc", c)
    monkeypatch.setattr(afk, "now_utc", c)
    return c


async def _bag(cid: int, code: str) -> int:
    async with get_sessionmaker()() as db:
        return await crafting.count_in_bag(db, cid, code)


async def _prof_xp(staff, cid, code, amount=10**7):  # type: ignore[no-untyped-def]
    r = await staff.http.post(
        f"/api/v1/admin/characters/{cid}/professions/{code}/xp",
        json={"amount": amount, "reason": "t"},
        headers={"Idempotency-Key": _key()},
    )
    assert r.status_code == 200, r.text


async def _craft(u, cid, recipe, qty, key=None):  # type: ignore[no-untyped-def]
    return await u.http.post(
        f"/api/v1/characters/{cid}/crafts",
        json={"recipe_code": recipe, "quantity": qty},
        headers={"Idempotency-Key": key or _key()},
    )


def test_engine_is_deterministic() -> None:
    entries = [
        {"template_code": "a", "weight": 90, "min": 1, "max": 2},
        {"template_code": "b", "weight": 10, "min": 1, "max": 1, "rare": True},
    ]
    kw = {
        "entries": entries,
        "node_tier": 0,
        "actions_per_hour": 120,
        "speed_pct": 0,
        "yield_pct": 100,
        "rare_find_pct": 0,
    }
    one = engine.resolve_gathering(CFG, segments=[(3600, 1.0)], seed=7, **kw)  # type: ignore[arg-type]
    assert one == engine.resolve_gathering(CFG, segments=[(3600, 1.0)], seed=7, **kw)  # type: ignore[arg-type]
    assert one["actions"] == 120 and one["materials"]["a"] > one["materials"].get("b", 0)
    half = engine.resolve_gathering(CFG, segments=[(3600, 0.5)], seed=7, **kw)  # type: ignore[arg-type]
    assert half["xp"] < one["xp"] and sum(half["materials"].values()) < sum(one["materials"].values())
    rolls = [{"tier_from": 0, "tier_to": 3, "min": 5, "max": 9}]
    assert engine.reroll_value(rolls, 1, 3) == engine.reroll_value(rolls, 1, 3)
    assert all(5 <= (engine.reroll_value(rolls, 1, s) or 0) <= 9 for s in range(50))
    assert engine.reroll_value(rolls, 5, 1) is None
    assert engine.fail_chance(CFG, 10, 500, 50) == CFG.min_fail_chance_pct


def test_loot_modifier_caps() -> None:
    class _P:
        effects = [{"effect_type": "LOOT_MODIFIER", "params": {"scope": "gold", "percent": 20}}] * 3

    class _Snap:
        player = _P()
        afk = afk_engine.AfkBalance.model_validate(load_yaml("balance/afk.yaml")["data"])

    mods = afk_engine.loot_modifiers(_Snap())  # type: ignore[arg-type]
    assert mods == {"gold": _Snap.afk.loot_modifier_caps["gold"]}


async def test_craft_queue_reservation_and_idempotent_claim(make_client, make_character, cclock) -> None:  # type: ignore[no-untyped-def]
    staff, u, cid = await _hero(make_client, make_character, level=50)
    await _grant(staff, cid, "copper_ore", 9)
    recipes = (await u.http.get(f"/api/v1/characters/{cid}/recipes?profession=blacksmithing")).json()
    smelt = next(r for r in recipes if r["code"] == "smelt_iron_ingot")
    assert smelt["known"] and smelt["craftable"] and smelt["max_craftable"] == 3
    key = _key()
    job = await _craft(u, cid, "smelt_iron_ingot", 3, key)
    assert job.status_code == 200, job.text
    assert (await _craft(u, cid, "smelt_iron_ingot", 3, key)).json()["id"] == job.json()["id"]  # replay
    assert await _bag(cid, "copper_ore") == 0  # reserved (consumed) at start
    assert (await _craft(u, cid, "smelt_iron_ingot", 1)).json()["error"]["code"] == "missing_materials"
    jid = job.json()["id"]
    early = await u.http.post(f"/api/v1/characters/{cid}/crafts/{jid}/claim", headers={"Idempotency-Key": _key()})
    assert early.json()["error"]["code"] == "craft_not_finished"
    cclock.now += timedelta(seconds=61)
    ck = _key()
    claim = await u.http.post(f"/api/v1/characters/{cid}/crafts/{jid}/claim", headers={"Idempotency-Key": ck})
    assert claim.status_code == 200, claim.text
    body = claim.json()
    assert body["successes"] == 3 and body["outputs"] == {"common": 3} and body["profession_xp"]["xp_gained"] > 0
    assert await _bag(cid, "iron_ingot") == 3
    again = await u.http.post(f"/api/v1/characters/{cid}/crafts/{jid}/claim", headers={"Idempotency-Key": ck})
    assert again.json()["replayed"] and await _bag(cid, "iron_ingot") == 3
    other = await u.http.post(f"/api/v1/characters/{cid}/crafts/{jid}/claim", headers={"Idempotency-Key": _key()})
    assert other.json()["error"]["code"] == "craft_claimed"
    assert (await u.http.get(f"/api/v1/characters/{cid}/crafts")).json() == []


async def test_cancel_refunds_and_queue_limit(make_client, make_character, cclock) -> None:  # type: ignore[no-untyped-def]
    staff, u, cid = await _hero(make_client, make_character, level=50)
    await _grant(staff, cid, "copper_ore", 9)
    ids = [(await _craft(u, cid, "smelt_iron_ingot", 1)).json()["id"] for _ in range(CFG.max_active_jobs)]
    assert (await _craft(u, cid, "smelt_iron_ingot", 1)).json()["error"]["code"] == "craft_queue_full"
    assert await _bag(cid, "copper_ore") == 9 - 3 * CFG.max_active_jobs
    r = await u.http.post(f"/api/v1/characters/{cid}/crafts/{ids[0]}/cancel")
    assert r.status_code == 200, r.text
    assert await _bag(cid, "copper_ore") == 9 - 3 * (CFG.max_active_jobs - 1)
    assert (await u.http.post(f"/api/v1/characters/{cid}/crafts/{ids[0]}/cancel")).status_code == 409
    other_u = await make_client()
    assert (await other_u.http.post(f"/api/v1/characters/{cid}/crafts/{ids[1]}/cancel")).status_code == 404


async def test_recipe_scroll_learning(make_client, make_character) -> None:  # type: ignore[no-untyped-def]
    staff, u, cid = await _hero(make_client, make_character, level=50)
    rec = {r["code"]: r for r in (await u.http.get(f"/api/v1/characters/{cid}/recipes")).json()}
    assert not rec["build_treasure_sonar"]["known"]
    assert (await _craft(u, cid, "build_treasure_sonar", 1)).json()["error"]["code"] == "recipe_unknown"
    ore = await _grant(staff, cid, "copper_ore", 1)
    bad = await u.http.post(f"/api/v1/characters/{cid}/recipes/learn", json={"instance_id": ore})
    assert bad.json()["error"]["code"] == "not_a_recipe_scroll"
    scroll = await _grant(staff, cid, "schematic_treasure_sonar", 2)
    ok = await u.http.post(f"/api/v1/characters/{cid}/recipes/learn", json={"instance_id": scroll})
    assert ok.status_code == 200, ok.text
    assert await _bag(cid, "schematic_treasure_sonar") == 1
    dup = await u.http.post(f"/api/v1/characters/{cid}/recipes/learn", json={"instance_id": scroll})
    assert dup.json()["error"]["code"] == "recipe_known"
    rec = {r["code"]: r for r in (await u.http.get(f"/api/v1/characters/{cid}/recipes")).json()}
    assert rec["build_treasure_sonar"]["known"] and not rec["build_treasure_sonar"]["craftable"]  # level 150 needed


async def test_crafted_gear_quality_is_separate_from_rarity(make_client, make_character, cclock) -> None:  # type: ignore[no-untyped-def]
    staff, u, cid = await _hero(make_client, make_character, level=50)
    await _prof_xp(staff, cid, "weaponsmithing")
    assert (await _craft(u, cid, "forge_militia_axe", 1)).json()["error"]["code"] == "tool_required"
    kit = await _grant(staff, cid, "apprentice_forge_kit")
    eq = await u.http.post(f"/api/v1/characters/{cid}/equipment/equip", json={"instance_id": kit})
    assert eq.status_code == 200, eq.text
    await _grant(staff, cid, "iron_ingot", 24)
    await _grant(staff, cid, "ironwood_log", 6)
    job = await _craft(u, cid, "forge_militia_axe", 6)
    assert job.status_code == 200, job.text
    cclock.now += timedelta(hours=1)
    res = (
        await u.http.post(
            f"/api/v1/characters/{cid}/crafts/{job.json()['id']}/claim", headers={"Idempotency-Key": _key()}
        )
    ).json()
    assert res["successes"] + res["failures"] == 6 and res["successes"] > 0
    inv = (await u.http.get(f"/api/v1/characters/{cid}/inventory")).json()
    axes = [i for i in inv["items"] if i["template_code"] == "militia_axe"]
    assert len(axes) == res["successes"]
    assert all(a["quality"] in {"common", *res["quality_chances"]} and a["rarity"] == "fine" for a in axes)


async def test_afk_gathering_session(make_client, make_character, cclock) -> None:  # type: ignore[no-untyped-def]
    u, cid = await afk_hero(make_client, make_character)
    bad = await _start(u, cid, duration=3600, profession_task={"node_code": "marsh_eels"})
    assert bad.json()["error"]["code"] == "invalid_gathering_node"
    s = await _start(u, cid, duration=3600, profession_task={"node_code": "meadow_herbs"})
    assert s.status_code == 201, s.text
    cclock.now += timedelta(hours=1)
    key = _key()
    c = await u.http.post(f"/api/v1/characters/{cid}/afk/claim", headers={"Idempotency-Key": key})
    assert c.status_code == 200, c.text
    prof = c.json()["profession"]
    assert prof["node_code"] == "meadow_herbs" and prof["actions"] > 0 and prof["materials"]["silverleaf"] > 0
    assert prof["profession_xp"]["profession"] == "herbalism" and c.json()["result"]["fights"] == 0
    assert await _bag(cid, "silverleaf") == prof["materials"]["silverleaf"]
    replay = await u.http.post(f"/api/v1/characters/{cid}/afk/claim", headers={"Idempotency-Key": key})
    assert replay.status_code == 200 and await _bag(cid, "silverleaf") == prof["materials"]["silverleaf"]


async def test_enchanting_reroll_imbue_and_salvage_ledger(make_client, make_character) -> None:  # type: ignore[no-untyped-def]
    staff, u, cid = await _hero(make_client, make_character, level=50)
    axe = await _grant(staff, cid, "militia_axe")
    await _grant(staff, cid, "arcane_dust", 40)
    base = f"/api/v1/characters/{cid}/items/{axe}"
    low = await u.http.post(f"{base}/reroll", json={"affix_index": 0}, headers={"Idempotency-Key": _key()})
    assert low.json()["error"]["code"] == "profession_level_low"
    await _prof_xp(staff, cid, "enchanting")
    poor = await u.http.post(f"{base}/reroll", json={"affix_index": 0}, headers={"Idempotency-Key": _key()})
    assert poor.status_code == 409  # no gold
    async with get_sessionmaker()() as db:
        await wallet.change_gold(db, character_id=cid, delta=5000, reason="test", idempotency_key=_key())
        await db.commit()
    dust = await _bag(cid, "arcane_dust")
    key = _key()
    r = await u.http.post(f"{base}/reroll", json={"affix_index": 0}, headers={"Idempotency-Key": key})
    assert r.status_code == 200, r.text
    assert r.json()["cost"]["gold"] == CFG.enchanting.reroll_gold_base + CFG.enchanting.reroll_gold_per_tier
    assert await _bag(cid, "arcane_dust") < dust
    again = await u.http.post(f"{base}/reroll", json={"affix_index": 0}, headers={"Idempotency-Key": key})
    assert again.json()["replayed"] and again.json()["after"] == r.json()["after"]
    im = await u.http.post(f"{base}/imbue", json={"imbue_code": "imbue_keen_edge"}, headers={"Idempotency-Key": _key()})
    assert im.status_code == 200, im.text
    bad = await u.http.post(f"{base}/imbue", json={"imbue_code": "imbue_warding"}, headers={"Idempotency-Key": _key()})
    assert bad.json()["error"]["code"] == "imbue_incompatible"
    inv = (await u.http.get(f"/api/v1/characters/{cid}/inventory")).json()
    item = next(i for i in inv["items"] if i["id"] == axe)
    assert item["enchantments"][0]["code"] == "imbue_keen_edge"
    sk = _key()
    sal = await u.http.post(f"{base}/salvage", headers={"Idempotency-Key": sk})
    assert sal.status_code == 200, sal.text
    assert (await u.http.post(f"{base}/salvage", headers={"Idempotency-Key": sk})).json()["replayed"]
    assert all(i["id"] != axe for i in (await u.http.get(f"/api/v1/characters/{cid}/inventory")).json()["items"])
    async with get_sessionmaker()() as db:
        actions = list(
            (
                await db.execute(
                    select(EnchantEvent.action).where(EnchantEvent.character_id == cid).order_by(EnchantEvent.id)
                )
            ).scalars()
        )
        assert actions == ["reroll", "imbue", "salvage"]
        assert (
            await db.execute(
                select(func.count())
                .select_from(ItemInstance)
                .where(ItemInstance.id == axe, ItemInstance.location == "destroyed")
            )
        ).scalar_one() == 1
    _ = datetime.now(UTC)
