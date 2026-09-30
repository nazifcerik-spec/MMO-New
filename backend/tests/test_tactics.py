"""Phase 11: Active Tactics — safe DSL validation against the kit, loadout limits, modes, draft preview."""

import pytest

from app.services import tactics
from app.services.content.types.abilities import AbilityLimits
from tests.test_classes import _class_id

CANONICAL = [
    {"use": {"tag": "defensive"}, "when": [{"kind": "HP_PERCENT", "op": "lt", "value": 35}]},
    {"use": {"ability": "execution"}, "when": [{"kind": "TARGET_TYPE", "target_type": "boss"}]},
    {"use": {"tag": "aoe"}, "when": [{"kind": "ENEMY_COUNT", "op": "gte", "value": 3}]},
    {"use": {"tag": "spender"}, "when": [{"kind": "RESOURCE_PERCENT", "op": "gte", "value": 70}]},
    {"use": {"ability": "war_cry"}, "when": [{"kind": "COOLDOWN_READY"}]},
]


async def _warrior(make_client, make_character, level: int = 100):  # type: ignore[no-untyped-def]
    u = await make_client()
    cid = await make_character(u.user_id, level=level, base_class_id=await _class_id("warrior"))
    body = (await u.http.get(f"/api/v1/characters/{cid}/afk-profile")).json()
    return u, cid, body


async def test_options_expose_registry_kit_and_canonical_template(make_client, make_character) -> None:  # type: ignore[no-untyped-def]
    _, _, body = await _warrior(make_client, make_character)
    t = body["options"]["tactics"]
    assert body["profile"]["mode"] == body["options"]["default_mode"] == "HYBRID"
    assert t["max_rules"] == 6 and t["max_core_actives"] == 5 and t["max_ultimates"] == 1
    required = {"HP_PERCENT", "RESOURCE_PERCENT", "TARGET_TYPE", "ENEMY_COUNT", "COOLDOWN_READY"}
    assert required <= set(t["condition_kinds"])
    assert {a["code"] for a in t["abilities"]} == {"shield_slam", "war_cry", "execution", "whirlwind", "last_stand"}
    assert [r["use"]["tag"] for r in t["template"]] == ["defensive", "finisher", "aoe", "spender", "buff"]
    assert set(t["decision_encounters"]) == {"boss", "arena"}


async def test_save_canonical_tactics_and_reject_unsafe_or_foreign_rules(make_client, make_character) -> None:  # type: ignore[no-untyped-def]
    u, cid, body = await _warrior(make_client, make_character)
    url = f"/api/v1/characters/{cid}/afk-profile"
    v = body["profile"]["version"]
    ok = await u.http.put(url, json={"expected_version": v, "mode": "ACTIVE_TACTICS", "tactics": CANONICAL})
    assert ok.status_code == 200, ok.text
    assert ok.json()["tactics"] == CANONICAL and ok.json()["mode"] == "ACTIVE_TACTICS"
    v = ok.json()["version"]
    bad = [
        ([{"use": {"ability": "fireball"}}], "tactic_ability_unavailable"),  # mage ability
        ([{"use": {"ability": "titans_wrath"}}], "tactic_ability_unavailable"),  # ultimate locked until Lv600
        ([{"use": {"tag": "song"}}], "tactic_tag_unavailable"),
        ([{"use": {"tag": "aoe"}}] * 7, "invalid_tactics"),
        ([{"use": {"tag": "aoe"}, "when": [{"kind": "EVAL", "value": 1}]}], "invalid_tactics"),
        ([{"use": {"tag": "aoe"}, "when": [{"kind": "HP_PERCENT", "op": "__import__"}]}], "invalid_tactics"),
        ([{"use": {"ability": "x; DROP TABLE users"}}], "invalid_tactics"),
        ([{"use": {"tag": "aoe"}, "expr": "1+1"}], "invalid_tactics"),
    ]
    for rules, code in bad:
        r = await u.http.put(url, json={"expected_version": v, "tactics": rules})
        assert r.status_code == 422 and r.json()["error"]["code"] == code, (rules, r.text)


async def test_loadout_limit_uses_ability_limits(make_client, make_character, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    real = tactics.get_published_balance

    async def fake(db, code, schema):  # type: ignore[no-untyped-def]
        if code == "ability_limits":
            return AbilityLimits(max_core_actives=2, max_ultimates=1, max_passives=10)
        return await real(db, code, schema)

    monkeypatch.setattr(tactics, "get_published_balance", fake)
    u, cid, _ = await _warrior(make_client, make_character)
    three = [{"use": {"ability": a}} for a in ("shield_slam", "war_cry", "execution")]
    r = await u.http.put(f"/api/v1/characters/{cid}/afk-profile", json={"expected_version": 1, "tactics": three})
    assert r.status_code == 422 and r.json()["error"]["code"] == "tactics_loadout_limit"
    # the same ability referenced by several rules counts once
    dup = [{"use": {"ability": "shield_slam"}}, {"use": {"ability": "shield_slam"}}]
    ok = await u.http.put(f"/api/v1/characters/{cid}/afk-profile", json={"expected_version": 1, "tactics": dup})
    assert ok.status_code == 200, ok.text


async def test_draft_preview_counts_rule_usage_per_scenario(make_client, make_character) -> None:  # type: ignore[no-untyped-def]
    u, cid, _ = await _warrior(make_client, make_character)
    url = f"/api/v1/characters/{cid}/combat/preview"
    pack = (await u.http.post(url, json={"fights": 3, "enemies": 4, "tactics": CANONICAL})).json()
    boss = (await u.http.post(url, json={"fights": 3, "boss": True, "tactics": CANONICAL})).json()
    assert pack["draft"] and boss["draft"]
    uses = lambda out, i: out["rules"][i]["uses"]  # noqa: E731
    assert uses(pack, 2) > 0 and uses(boss, 2) == 0  # AoE only vs >=3 enemies
    assert uses(boss, 1) > 0 and uses(pack, 1) == 0  # boss finisher only vs bosses
    bad = await u.http.post(url, json={"fights": 1, "tactics": [{"use": {"ability": "fireball"}}]})
    assert bad.status_code == 422


async def test_hybrid_uses_tactics_only_in_decision_encounters(make_client, make_character) -> None:  # type: ignore[no-untyped-def]
    u, cid, body = await _warrior(make_client, make_character)
    only_warcry = [{"use": {"ability": "war_cry"}}]
    put = await u.http.put(
        f"/api/v1/characters/{cid}/afk-profile",
        json={"expected_version": body["profile"]["version"], "mode": "HYBRID", "tactics": only_warcry},
    )
    assert put.status_code == 200
    url = f"/api/v1/characters/{cid}/combat/preview"
    normal = (await u.http.post(url, json={"fights": 2})).json()
    boss = (await u.http.post(url, json={"fights": 2, "boss": True})).json()
    assert [r["ability"] for r in boss["rules"]] == ["war_cry"]  # player tactics drive the boss fight
    assert [r["ability"] for r in normal["rules"]] != ["war_cry"]  # ordinary AFK stays passive-first


@pytest.mark.parametrize("mode", ["PASSIVE_ONLY", "ACTIVE_TACTICS", "HYBRID"])
async def test_all_modes_selectable(make_client, make_character, mode: str) -> None:  # type: ignore[no-untyped-def]
    u, cid, body = await _warrior(make_client, make_character)
    r = await u.http.put(
        f"/api/v1/characters/{cid}/afk-profile", json={"expected_version": body["profile"]["version"], "mode": mode}
    )
    assert r.status_code == 200 and r.json()["mode"] == mode
