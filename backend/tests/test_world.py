"""Phase 12: PvE world content — seeds, scaling layers, deterministic encounters/drops, APIs, publish validators."""

import uuid

from sqlalchemy import select

from app.db.session import get_sessionmaker
from app.game_engine.rng import Rng
from app.game_engine.world import TierScaling, enemy_stats, generate_encounter, roll_drops
from app.models.world import Zone, ZoneTier
from app.services import world
from app.services.content.types.afk_profiles import RiskProfiles
from app.services.content.types.balance import get_published_balance
from app.services.content.types.world import EnemyScaling
from tests.test_classes import _class_id

TIER_LEVELS = {0: (1, 49), 1: (50, 99), 2: (100, 199), 3: (200, 299), 4: (300, 399), 5: (400, 499),
               6: (500, 599), 7: (600, 699), 8: (700, 849), 9: (850, 949), 10: (950, 1000)}  # fmt: skip
ADMIN = "/api/v1/admin/content"


async def test_sample_world_covers_every_tier(client) -> None:  # type: ignore[no-untyped-def]
    async with get_sessionmaker()() as s:
        tiers = {t.tier: t for t in (await s.execute(select(ZoneTier).where(ZoneTier.status == "published"))).scalars()}
        zones = list((await s.execute(select(Zone).where(Zone.status == "published"))).scalars())
        risks = await get_published_balance(s, "risk_profiles", RiskProfiles)
    assert {t: (v.min_level, v.max_level) for t, v in tiers.items()} == TIER_LEVELS
    by_tier = {tiers[t].code: 0 for t in tiers}
    for z in zones:
        by_tier[z.tier_code] += 1
        assert z.encounter_pool and z.boss_pool and z.drop_table_code
    assert all(n >= 1 for n in by_tier.values())
    xp = {c: (p.xp_loot_percent, p.rare_bonus_percent) for c, p in risks.profiles.items()}
    assert xp == {"safe": (85, 0), "balanced": (100, 0), "dangerous": (120, 0), "elite_hunt": (135, 25)}


def test_enemy_and_tier_scaling_are_separate_layers() -> None:
    import yaml

    from app.content.loader import DATA_DIR

    cfg = EnemyScaling.model_validate(yaml.safe_load((DATA_DIR / "balance/enemy_scaling.yaml").read_text())["data"])
    t0 = TierScaling(hp_pct=100, attack_pct=100, defense_pct=100, xp_pct=100, gold_pct=100)
    t10 = TierScaling(hp_pct=120, attack_pct=110, defense_pct=110, xp_pct=120, gold_pct=140)
    kw = {"rank": "normal", "archetype": "brute", "stat_mods": {}}
    low, high = enemy_stats(cfg, t0, 100, **kw), enemy_stats(cfg, t0, 500, **kw)  # type: ignore[arg-type]
    tiered = enemy_stats(cfg, t10, 100, **kw)  # type: ignore[arg-type]
    assert high["max_hp"] > low["max_hp"] and tiered["max_hp"] == round(low["max_hp"] * 1.2, 4)
    boss = enemy_stats(cfg, t0, 100, rank="boss", archetype="brute", stat_mods={})
    elite = enemy_stats(cfg, t0, 100, rank="elite", archetype="brute", stat_mods={})
    assert boss["max_hp"] > elite["max_hp"] > low["max_hp"]
    dodgy = enemy_stats(
        cfg.model_copy(update={"dodge": 30}), t0, 100, rank="normal", archetype="skirmisher", stat_mods={"dodge": 500}
    )
    assert dodgy["dodge"] == cfg.dodge_cap


async def test_bundle_generates_deterministic_encounters_and_distinct_bosses(client) -> None:  # type: ignore[no-untyped-def]
    async with get_sessionmaker()() as s:
        bundle = await world.load_bundle(s, "ironroot_forest")
    a = generate_encounter(bundle, Rng(5), 150)
    b = generate_encounter(bundle, Rng(5), 150)
    assert a == b and not a.boss and all(not e.is_boss for e in a.enemies) and 1 <= len(a.enemies) <= 5
    boss = generate_encounter(bundle, Rng(5), 150, force_boss=True)
    assert boss.boss and boss.enemies[0].is_boss and boss.code == "heartwood_colossus"
    assert len(boss.enemies) == 2  # boss + add (tier >= 2)
    assert any(e["effect_type"] == "THRESHOLD_TRIGGER" for e in boss.enemies[0].effects)
    assert generate_encounter(bundle, Rng(5), 5).level == bundle.min_level  # clamped to zone range
    assert generate_encounter(bundle, Rng(5), 900).level == bundle.max_level
    seen = {generate_encounter(bundle, Rng(i), 150).code for i in range(200)}
    assert {"ironroot_forest_pack", "ironroot_forest_hunters", "ironroot_forest_elite"} <= seen
    assert bundle.model_validate_json(bundle.model_dump_json()) == bundle  # snapshot-able


async def test_drop_rolls_are_deterministic_and_respect_boss_only(client) -> None:  # type: ignore[no-untyped-def]
    async with get_sessionmaker()() as s:
        bundle = await world.load_bundle(s, "whispering_meadows")
    table = bundle.drop_tables["old_greymane_drops"]
    one = roll_drops(Rng(9), table.rolls, table.entries, boss=True)
    assert one == roll_drops(Rng(9), table.rolls, table.entries, boss=True)
    for seed in range(50):
        for d in roll_drops(Rng(seed), 3, table.entries, boss=False):
            assert not d.get("boss_only")
    entries = ({"kind": "item_pool", "tier": 0, "weight": 1, "chance_pct": 40, "rare": True},)
    base = sum(len(roll_drops(Rng(i), 1, entries, boss=False)) for i in range(2000))
    boosted = sum(len(roll_drops(Rng(i), 1, entries, boss=False, rare_bonus_pct=25)) for i in range(2000))
    assert boosted > base


async def test_zone_list_eligibility_pagination_and_access(make_client, make_character) -> None:  # type: ignore[no-untyped-def]
    u = await make_client()
    cid = await make_character(u.user_id, level=60, base_class_id=await _class_id("warrior"))
    page1 = (await u.http.get("/api/v1/zones", params={"character_id": cid, "limit": 5})).json()
    assert len(page1["items"]) == 5 and page1["next_cursor"] is not None
    page2 = (await u.http.get("/api/v1/zones", params={"character_id": cid, "after": page1["next_cursor"]})).json()
    codes = [z["code"] for z in page1["items"] + page2["items"]]
    assert len(codes) == len(set(codes)) >= 11
    by = {z["code"]: z for z in page1["items"] + page2["items"]}
    assert by["whispering_meadows"]["eligible"] and by["mistfen_marsh"]["eligible"]
    assert not by["ironroot_forest"]["eligible"] and by["ironroot_forest"]["unmet"][0]["kind"] == "min_level"
    anon = await make_client()
    await anon.http.post("/api/v1/auth/logout")
    assert (await anon.http.get("/api/v1/zones")).status_code == 200
    other = await make_client()
    assert (await other.http.get("/api/v1/zones", params={"character_id": cid})).status_code == 404
    assert (await u.http.get("/api/v1/zones/nope")).status_code == 404


async def test_zone_detail_localized(make_client) -> None:  # type: ignore[no-untyped-def]
    u = await make_client()
    en = (await u.http.get("/api/v1/zones/sunscar_dunes")).json()
    tr = (await u.http.get("/api/v1/zones/sunscar_dunes", headers={"Accept-Language": "tr"})).json()
    assert en["name"] == "Sunscar Dunes" and tr["name"] == "Güneşyarası Kumulları"
    assert en["tier"] == 3 and len(en["enemies"]) == 3 and en["bosses"][0]["code"] == "pharaoh_of_ash"
    assert {r["code"] for r in en["risk_profiles"]} == {"safe", "balanced", "dangerous", "elite_hunt"}
    assert any(d["kind"] == "gold" for d in en["drops"])


async def test_zone_preview_uses_real_encounters(make_client, make_character) -> None:  # type: ignore[no-untyped-def]
    u = await make_client()
    cid = await make_character(u.user_id, level=30, unspent=87, base_class_id=await _class_id("warrior"))
    prog = (await u.http.get(f"/api/v1/characters/{cid}/progression")).json()
    auto = await u.http.post(
        f"/api/v1/characters/{cid}/stats/auto",
        json={"profile_code": "physical_dps", "expected_version": prog["version"]},
        headers={"Idempotency-Key": f"auto-stats-{cid}"},
    )
    assert auto.status_code == 200, auto.text
    url = f"/api/v1/characters/{cid}/zones/whispering_meadows/preview"
    r = await u.http.post(url, json={"fights": 5, "potions": 0})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["zone"] == "whispering_meadows" and sum(out["encounters"].values()) == 5
    assert out["win_rate"] >= 0.6
    assert r.json() == (await u.http.post(url, json={"fights": 5, "potions": 0})).json()
    boss = (await u.http.post(url, json={"fights": 1, "boss": True})).json()
    assert boss["encounters"] == {"old_greymane": 1}


def _zone(**over):  # type: ignore[no-untyped-def]
    data = {
        "tier_code": "t2",
        "min_level": 100,
        "recommended_level": 150,
        "max_level": 199,
        "danger_rating": 3,
        "encounter_pool": [{"encounter_code": "ironroot_forest_pack", "weight": 1}],
    }
    return {**data, **over}


async def _issues(gd, entity: str, data: dict) -> set[str]:  # type: ignore[no-untyped-def]
    code = f"t_{uuid.uuid4().hex[:10]}"
    r = await gd.http.post(f"{ADMIN}/{entity}", json={"code": code, "data": data})
    assert r.status_code == 201, r.text
    v = (await gd.http.post(f"{ADMIN}/{entity}/{code}/validate")).json()
    return {i["code"] for i in v["issues"]}


async def test_publish_validators(make_client) -> None:  # type: ignore[no-untyped-def]
    gd = await make_client("game_designer")
    assert await _issues(gd, "zone", _zone()) == set()
    assert "empty_encounter_pool" in await _issues(gd, "zone", _zone(encounter_pool=[]))
    bad = await gd.http.post(
        f"{ADMIN}/zone", json={"code": "t_badrange", "data": _zone(min_level=160, recommended_level=150)}
    )
    assert bad.status_code == 422 and "invalid_level_range" in bad.text
    assert "invalid_level_range" in await _issues(
        gd, "zone", _zone(min_level=600, recommended_level=650, max_level=700)
    )
    assert "unknown_reference" in await _issues(
        gd, "zone", _zone(encounter_pool=[{"encounter_code": "x_x", "weight": 1}])
    )
    assert "zone_unreachable" in await _issues(
        gd, "zone", _zone(requirements=[{"kind": "zone_cleared", "code": "throne_of_eternity"}])
    )
    assert "zone_unreachable" in await _issues(gd, "zone", _zone(requirements=[{"kind": "min_level", "value": 500}]))
    # circular prerequisite: A requires B, then B requires A
    a, b = f"cyc_a_{uuid.uuid4().hex[:6]}", f"cyc_b_{uuid.uuid4().hex[:6]}"
    await gd.http.post(
        f"{ADMIN}/zone", json={"code": a, "data": _zone(requirements=[{"kind": "zone_cleared", "code": b}])}
    )
    await gd.http.post(
        f"{ADMIN}/zone", json={"code": b, "data": _zone(requirements=[{"kind": "zone_cleared", "code": a}])}
    )
    v = (await gd.http.post(f"{ADMIN}/zone/{b}/validate")).json()
    assert "circular_prerequisite" in {i["code"] for i in v["issues"]} and not v["ok"]
    # impossible enemy stats -> warning only
    enemy = f"t_{uuid.uuid4().hex[:8]}"
    r = await gd.http.post(
        f"{ADMIN}/enemy",
        json={"code": enemy, "data": {"family": "test", "archetype": "tank", "stat_mods": {"max_hp": 500}}},
    )
    assert r.status_code == 201
    enc = f"t_{uuid.uuid4().hex[:8]}"
    await gd.http.post(
        f"{ADMIN}/encounter", json={"code": enc, "data": {"members": [{"enemy_code": enemy, "min": 1, "max": 1}]}}
    )
    hard = _zone(
        tier_code="t10",
        min_level=950,
        recommended_level=975,
        max_level=1000,
        encounter_pool=[{"encounter_code": enc, "weight": 1}],
    )
    codes = await _issues(gd, "zone", hard)
    assert "impossible_enemy_stats" in codes and "reference_unpublished" in codes
    assert "empty_encounter" in await _issues(gd, "encounter", {"members": []})
    assert "invalid_damage_type" in await _issues(
        gd, "enemy", {"family": "t", "archetype": "brute", "damage_type": "sonic"}
    )
    zap = {"code": "zap", "effects": [{"effect_type": "DAMAGE", "params": {"percent_of_power": 50}}]}
    bad_rule = {"abilities": [zap], "rules": [{"use": {"ability": "not_mine"}}]}
    assert "unknown_reference" in await _issues(gd, "enemy_ability_profile", bad_rule)
    player = await make_client()
    assert (await player.http.post(f"{ADMIN}/zone", json={"code": "zz_zz", "data": _zone()})).status_code == 403
