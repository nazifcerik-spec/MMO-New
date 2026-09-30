"""Phase 17: professions — catalog, independent XP, licenses, specializations, modifiers, tools, quality."""

import uuid
from datetime import timedelta

from app.content.loader import load_yaml
from app.db.session import get_sessionmaker
from app.game_engine import professions as rules
from app.game_engine.rng import Rng
from app.models.character import Character
from app.services import professions, wallet
from tests.test_classes import _class_id

CFG = rules.ProfessionConfig.model_validate(load_yaml("balance/professions.yaml")["data"])


def _key() -> str:
    return f"k-{uuid.uuid4().hex}"


def test_ranks_curve_and_tools() -> None:
    assert [rules.rank_for(CFG, lvl) for lvl in (1, 99, 100, 200, 399, 400, 500)] == [
        "apprentice", "apprentice", "journeyman", "expert", "artisan", "master", "grandmaster",
    ]  # fmt: skip
    assert rules.xp_to_next(CFG, 500) is None and rules.xp_to_next(CFG, 1) < rules.xp_to_next(CFG, 300)  # type: ignore[operator]
    capped = rules.apply_xp(CFG, 190, 0, 10**9, licensed=False)
    assert capped.level == 199 and capped.capped_by_license
    assert rules.apply_xp(CFG, 190, 0, 10**12, licensed=True).level == 500
    assert rules.tool_yield_pct(CFG, 0, 0) == 100 and rules.tool_yield_pct(CFG, 5, 2) == 109
    assert rules.tool_yield_pct(CFG, 0, 2) == 30 and rules.tool_yield_pct(CFG, None, 5) == CFG.tools.min_yield_pct
    assert rules.node_level_required(CFG, 0) == 1 and rules.node_level_required(CFG, 4) == 200


def test_quality_roll_is_deterministic_and_skill_improves_it() -> None:
    low = rules.quality_chances(CFG, profession_level=100, recipe_level=100, bonus_pct=0)
    high = rules.quality_chances(CFG, profession_level=500, recipe_level=100, bonus_pct=20)
    assert all(high[q] > low[q] for q in low)
    draws = [rules.roll_quality(CFG, high, Rng(s)) for s in range(2000)]
    assert draws == [rules.roll_quality(CFG, high, Rng(s)) for s in range(2000)]
    assert draws.count("common") > draws.count("fine") > draws.count("superior") > 0


async def test_catalog_is_canonical_and_localized(client) -> None:  # type: ignore[no-untyped-def]
    en = (await client.get("/api/v1/content/professions")).json()
    assert len(en) == 15 and all(len(p["specializations"]) == 2 for p in en)
    by = {p["code"]: p for p in en}
    assert by["mining"]["stats"] == ["STR", "VIT"] and by["fishing"]["stats"] == ["DEX", "LUK"]
    assert by["herbalism"]["stats"] == ["WIS", "LUK"] and by["enchanting"]["stats"] == ["INT", "SPI"]
    assert by["mining"]["title"] == "Grandmaster Miner" and by["blacksmithing"]["title"] == "Grandmaster Blacksmith"
    assert [s["code"] for s in by["engineering"]["specializations"]] == ["mechanist", "trapwright"]
    tr = {
        p["code"]: p
        for p in (await client.get("/api/v1/content/professions", headers={"Accept-Language": "tr"})).json()
    }
    assert tr["mining"]["name"] == "Madencilik"


async def _hero(make_client, make_character, race: str | None = None):  # type: ignore[no-untyped-def]
    u = await make_client()
    kwargs = {}
    if race:
        from sqlalchemy import select

        from app.models.race import Race

        async with get_sessionmaker()() as db:
            kwargs["race_id"] = (await db.execute(select(Race.id).where(Race.code == race))).scalar_one()
    cid = await make_character(u.user_id, level=50, base_class_id=await _class_id("warrior"), **kwargs)
    return u, cid


async def _xp(staff, cid, code, amount):  # type: ignore[no-untyped-def]
    r = await staff.http.post(
        f"/api/v1/admin/characters/{cid}/professions/{code}/xp",
        json={"amount": amount, "reason": "t"},
        headers={"Idempotency-Key": _key()},
    )
    assert r.status_code == 200, r.text
    return r.json()


async def test_xp_is_independent_capped_without_license_and_awards_title(make_client, make_character) -> None:  # type: ignore[no-untyped-def]
    staff = await make_client("admin")
    u, cid = await _hero(make_client, make_character)
    before = (await u.http.get(f"/api/v1/characters/{cid}/progression")).json()
    out = await _xp(staff, cid, "mining", 10**9)
    assert out["level_after"] == 199 and out["capped_by_license"]
    after = (await u.http.get(f"/api/v1/characters/{cid}/progression")).json()
    assert (after["level"], after["xp"]) == (before["level"], before["xp"])  # character XP untouched
    lic = await u.http.post(
        f"/api/v1/characters/{cid}/professions/mining/license",
        json={"active": True},
        headers={"Idempotency-Key": _key()},
    )
    assert lic.status_code == 200 and lic.json()["cost_gold"] == 0
    done = await _xp(staff, cid, "mining", 10**9)
    assert done["level_after"] == 500 and done["title"] == "grandmaster_mining"
    view = (await u.http.get(f"/api/v1/characters/{cid}/professions")).json()
    mining = next(p for p in view["professions"] if p["code"] == "mining")
    assert mining["rank"] == "grandmaster" and mining["title_earned"] and mining["xp_to_next"] is None
    key = _key()
    r1 = await staff.http.post(
        f"/api/v1/admin/characters/{cid}/professions/fishing/xp",
        json={"amount": 500, "reason": "t"},
        headers={"Idempotency-Key": key},
    )
    r2 = await staff.http.post(
        f"/api/v1/admin/characters/{cid}/professions/fishing/xp",
        json={"amount": 500, "reason": "t"},
        headers={"Idempotency-Key": key},
    )
    assert r2.json()["replayed"] and r1.json()["level_after"] == r2.json()["level_after"]
    player = await make_client()
    assert (
        await player.http.post(
            f"/api/v1/admin/characters/{cid}/professions/mining/xp",
            json={"amount": 1, "reason": "x"},
            headers={"Idempotency-Key": _key()},
        )
    ).status_code == 403


async def test_license_limit_cooldown_and_cost(make_client, make_character, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    u, cid = await _hero(make_client, make_character)

    async def lic(code, active=True):  # type: ignore[no-untyped-def]
        return await u.http.post(
            f"/api/v1/characters/{cid}/professions/{code}/license",
            json={"active": active},
            headers={"Idempotency-Key": _key()},
        )

    for code in ("mining", "fishing", "alchemy"):
        assert (await lic(code)).json()["cost_gold"] == 0
    fourth = await lic("cooking")
    assert fourth.status_code == 409 and fourth.json()["error"]["code"] == "license_limit"
    assert (await lic("fishing", active=False)).status_code == 200
    cd = await lic("cooking")
    assert cd.status_code == 409 and cd.json()["error"]["code"] == "license_cooldown"
    base = professions.now_utc()
    monkeypatch.setattr(professions, "now_utc", lambda: base + timedelta(days=8))
    broke = await lic("cooking")
    assert broke.status_code == 409 and broke.json()["error"]["code"] == "insufficient_funds"
    async with get_sessionmaker()() as db:
        await wallet.change_gold(db, character_id=cid, delta=1000, reason="test", idempotency_key=_key())
        await db.commit()
    paid = await lic("cooking")
    assert paid.status_code == 200 and paid.json()["cost_gold"] == 500
    view = (await u.http.get(f"/api/v1/characters/{cid}/professions")).json()
    assert view["licenses"]["active"] == 3 and view["licenses"]["free_remaining"] == 0


async def test_specialization_requires_level_and_license(make_client, make_character) -> None:  # type: ignore[no-untyped-def]
    staff = await make_client("admin")
    u, cid = await _hero(make_client, make_character)

    async def spec(code, s):  # type: ignore[no-untyped-def]
        return await u.http.post(
            f"/api/v1/characters/{cid}/professions/{code}/specialize",
            json={"specialization_code": s},
            headers={"Idempotency-Key": _key()},
        )

    assert (await spec("mining", "prospector")).json()["error"]["code"] == "specialization_locked"
    await u.http.post(
        f"/api/v1/characters/{cid}/professions/mining/license",
        json={"active": True},
        headers={"Idempotency-Key": _key()},
    )
    await _xp(staff, cid, "mining", 10**7)
    assert (await spec("mining", "angler")).json()["error"]["code"] == "invalid_specialization"
    ok = await spec("mining", "prospector")
    assert ok.status_code == 200 and ok.json()["cost_gold"] == 0
    view = (await u.http.get(f"/api/v1/characters/{cid}/professions")).json()
    mining = next(p for p in view["professions"] if p["code"] == "mining")
    assert mining["modifiers"]["yield"] == 12 and mining["specialization_code"] == "prospector"
    swap = await spec("mining", "deep_miner")
    assert swap.status_code == 409 and swap.json()["error"]["code"] == "insufficient_funds"  # respec costs gold


async def test_modifiers_come_from_registry_sources_and_tools(make_client, make_character) -> None:  # type: ignore[no-untyped-def]
    staff = await make_client("admin")
    u, cid = await _hero(make_client, make_character, race="dwarf")
    no_tool = (await u.http.get(f"/api/v1/characters/{cid}/professions/mining/node-check", params={"tier": 0})).json()
    assert no_tool["modifiers"]["speed"] == 8 and no_tool["tool_tier"] is None and no_tool["tool_yield_pct"] == 65
    g = await staff.http.post(
        f"/api/v1/admin/characters/{cid}/items",
        json={"template_code": "novice_pickaxe", "reason": "t"},
        headers={"Idempotency-Key": _key()},
    )
    eq = await u.http.post(f"/api/v1/characters/{cid}/equipment/equip", json={"instance_id": g.json()["id"]})
    assert eq.status_code == 200, eq.text
    tooled = (await u.http.get(f"/api/v1/characters/{cid}/professions/mining/node-check", params={"tier": 0})).json()
    assert tooled["tool_tier"] == 0 and tooled["tool_yield_pct"] == 100 and tooled["modifiers"]["yield"] == 5
    high = (await u.http.get(f"/api/v1/characters/{cid}/professions/mining/node-check", params={"tier": 3})).json()
    assert not high["accessible"] and high["required_level"] == 150 and high["tool_yield_pct"] == max(10, 100 - 3 * 35)
    assert set(high["stat_bonuses"]) == {"speed", "quality"}
    async with get_sessionmaker()() as db:
        ch = await db.get(Character, cid)
        assert ch is not None
        effects = await professions.profession_effects(db, ch)
    assert all(e["effect_type"] != "DAMAGE" for e in effects if e.get("effect_type", "").startswith("PROFESSION"))
