"""Phase 10: AFK profile (presets / advanced) API and passive-only preview."""

from tests.test_classes import _class_id


async def _profile(u, cid):  # type: ignore[no-untyped-def]
    r = await u.http.get(f"/api/v1/characters/{cid}/afk-profile")
    assert r.status_code == 200
    return r.json()


async def test_default_profile_and_localized_options(make_client, make_character) -> None:  # type: ignore[no-untyped-def]
    u = await make_client()
    cid = await make_character(u.user_id, level=50, base_class_id=await _class_id("cleric"))
    body = await _profile(u, cid)
    p, o = body["profile"], body["options"]
    assert p["passive_profile_code"] == o["passive_profiles"][0]["code"]
    assert {s["code"] for s in o["stances"]} == {"aggressive", "guarded", "efficient"}
    assert {x["code"] for x in o["presets"]} >= {"safe_farmer", "balanced", "aggressive_hunter", "boss_hunter"}
    assert all(pp["code"].startswith("cleric_") for pp in o["passive_profiles"]) and len(o["passive_profiles"]) == 2
    tr = await u.http.get(f"/api/v1/characters/{cid}/afk-profile", headers={"Accept-Language": "tr"})
    assert tr.json()["options"]["stances"][0]["name"] != o["stances"][0]["name"]


async def test_preset_then_advanced_edit_and_version_conflict(make_client, make_character) -> None:  # type: ignore[no-untyped-def]
    u = await make_client()
    cid = await make_character(u.user_id, level=50, base_class_id=await _class_id("warrior"))
    v = (await _profile(u, cid))["profile"]["version"]
    url = f"/api/v1/characters/{cid}/afk-profile"
    r = await u.http.put(url, json={"expected_version": v, "preset_code": "safe_farmer"})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["stance"] == "guarded" and out["risk_level"] == "safe" and out["preset_code"] == "safe_farmer"
    v2 = r.json()["version"]
    assert v2 > v
    stale = await u.http.put(url, json={"expected_version": v, "stance": "aggressive"})
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "version_conflict"
    adv = await u.http.put(
        url,
        json={
            "expected_version": v2,
            "stance": "aggressive",
            "potion_threshold_pct": 25,
            "loot_filter": {"min_rarity": "rare", "min_tier": 3, "keep_materials": False},
        },
    )
    assert adv.status_code == 200
    out = adv.json()
    assert out["preset_code"] is None and out["stance"] == "aggressive" and out["potion_threshold_pct"] == 25
    assert out["loot_filter"]["min_rarity"] == "rare" and out["loot_filter"]["auto_salvage"] is False


async def test_profile_validation_denials(make_client, make_character) -> None:  # type: ignore[no-untyped-def]
    u = await make_client()
    cid = await make_character(u.user_id, level=50, base_class_id=await _class_id("warrior"))
    url = f"/api/v1/characters/{cid}/afk-profile"
    v = (await _profile(u, cid))["profile"]["version"]
    cases = [
        ({"stance": "balanced"}, "invalid_stance"),
        ({"target_priority": "random"}, "invalid_target_priority"),
        ({"risk_level": "suicidal"}, "invalid_risk"),
        ({"preset_code": "nope"}, "invalid_preset"),
        ({"passive_profile_code": "cleric_devout"}, "invalid_passive_profile"),
        ({"loot_filter": {"min_rarity": "godly"}}, "invalid_loot_filter"),
    ]
    for payload, code in cases:
        r = await u.http.put(url, json={"expected_version": v, **payload})
        assert r.status_code == 422 and r.json()["error"]["code"] == code, (payload, r.text)
    bad = await u.http.put(url, json={"expected_version": v, "potion_threshold_pct": 150})
    assert bad.status_code == 422
    other = await make_client()
    assert (await other.http.get(url)).status_code == 404
    assert (await other.http.put(url, json={"expected_version": v, "stance": "guarded"})).status_code == 404


async def test_preview_is_deterministic_and_reports_rules(make_client, make_character) -> None:  # type: ignore[no-untyped-def]
    u = await make_client()
    cid = await make_character(u.user_id, level=100, base_class_id=await _class_id("warrior"))
    url = f"/api/v1/characters/{cid}/combat/preview"
    a = await u.http.post(url, json={"fights": 3, "potions": 2})
    b = await u.http.post(url, json={"fights": 3, "potions": 2})
    assert a.status_code == 200 and a.json() == b.json()
    out = a.json()
    assert 0 <= out["win_rate"] <= 1 and out["avg_duration_s"] > 0 and out["avg_potions_used"] <= 2
    assert out["rules"] and sum(r["uses"] for r in out["rules"]) > 0
    assert (await u.http.post(url, json={"fights": 51})).status_code == 422


async def test_support_class_is_solo_viable_passive_only(make_client, make_character) -> None:  # type: ignore[no-untyped-def]
    """Support solo: canonical solo conversion + heal-threshold rules keep a cleric alive and killing."""
    u = await make_client()
    for cls in ("cleric", "bard", "shaman"):
        cid = await make_character(u.user_id, level=100, base_class_id=await _class_id(cls))
        v = (await _profile(u, cid))["profile"]["version"]
        put = await u.http.put(
            f"/api/v1/characters/{cid}/afk-profile", json={"expected_version": v, "mode": "PASSIVE_ONLY"}
        )
        assert put.status_code == 200
        out = (await u.http.post(f"/api/v1/characters/{cid}/combat/preview", json={"fights": 3, "potions": 0})).json()
        assert out["win_rate"] == 1.0 and out["death_rate"] == 0.0, (cls, out)
        assert out["avg_damage_dealt"] > 0
