import uuid

from sqlalchemy import select

from app.db.session import get_sessionmaker
from app.models.abilities import AbilityDefinition, TalentNode, TalentTree
from tests.test_classes import _class_id

CAPSTONES = {
    "warrior": {"living_fortress", "perfect_technique_warrior", "blood_frenzy"},
    "cleric": {"miracle", "divine_fortress", "divine_presence"},
}


async def test_thirty_trees_three_per_class_one_capstone_each(client) -> None:  # type: ignore[no-untyped-def]
    async with get_sessionmaker()() as s:
        trees = list((await s.execute(select(TalentTree).where(TalentTree.status == "published"))).scalars())
        nodes = list(
            (
                await s.execute(select(TalentNode).where(TalentNode.status == "published", TalentNode.is_capstone))
            ).scalars()
        )
    by_class: dict[str, int] = {}
    for t in trees:
        by_class[t.base_class_code] = by_class.get(t.base_class_code, 0) + 1
    assert len(by_class) == 10 and set(by_class.values()) == {3}
    caps_by_tree: dict[str, int] = {}
    for n in nodes:
        caps_by_tree[n.tree_code] = caps_by_tree.get(n.tree_code, 0) + 1
        assert n.required_level == 850 and n.required_points_in_tree == 24
    assert len(caps_by_tree) == 30 and set(caps_by_tree.values()) == {1}
    for cls, caps in CAPSTONES.items():
        assert {n.code for n in nodes if n.tree_code.startswith(cls + "_")} == caps


async def test_spec_kits_respect_5_actives_1_ultimate(client) -> None:  # type: ignore[no-untyped-def]
    async with get_sessionmaker()() as s:
        abilities = list((await s.execute(select(AbilityDefinition))).scalars())
    for cls in {a.owner_code for a in abilities}:
        mine = [a for a in abilities if a.owner_code == cls]
        assert sum(a.ability_type == "ACTIVE" for a in mine) <= 5
        assert sum(a.ability_type == "ULTIMATE" for a in mine) == 1


async def test_talent_allocation_flow(make_client, make_character) -> None:  # type: ignore[no-untyped-def]
    u = await make_client()
    cid = await make_character(u.user_id, level=900, base_class_id=await _class_id("warrior"))
    view = (await u.http.get(f"/api/v1/characters/{cid}/talents", params={"locale": "tr"})).json()
    assert view["points_available"] == 41 and [t["name"] for t in view["trees"]] == ["Savunma", "Silahlar", "Kan"]
    ver = view["version"]
    url = f"/api/v1/characters/{cid}/talents"
    locked = await u.http.post(url, json={"allocations": {"warrior_defense_n3": 1}, "expected_version": ver})
    assert locked.status_code == 422 and locked.json()["error"]["code"] == "tier_locked"
    tree = "warrior_defense"
    plan = {
        f"{tree}_n1": 5,
        f"{tree}_n2": 3,
        f"{tree}_n3": 5,
        f"{tree}_n4": 3,
        f"{tree}_n5": 5,
        f"{tree}_n7": 2,
        f"{tree}_n9": 1,
        "living_fortress": 1,
    }
    ok = await u.http.post(url, json={"allocations": plan, "expected_version": ver})
    assert ok.status_code == 200, ok.text
    assert ok.json()["points_spent"] == 25 and ok.json()["trees"][0]["spent"] == 25
    stale = await u.http.post(url, json={"allocations": {"warrior_arms_n1": 1}, "expected_version": ver})
    assert stale.status_code == 409
    ver2 = ok.json()["version"]
    down = await u.http.post(url, json={"allocations": {f"{tree}_n1": 4}, "expected_version": ver2})
    assert down.status_code == 422 and down.json()["error"]["code"] == "talent_decrease"
    over = await u.http.post(url, json={"allocations": {f"{tree}_n6": 1}, "expected_version": ver2})
    assert over.status_code == 422 and over.json()["error"]["code"] == "tree_cap"
    second_cap = await u.http.post(url, json={"allocations": {"blood_frenzy": 1}, "expected_version": ver2})
    assert second_cap.status_code == 422
    prog = (await u.http.get(f"/api/v1/characters/{cid}/progression")).json()
    hp = prog["stats"]["derived"]["max_hp"]["breakdown"]
    assert any(b["source"] == "talent" and b["ref"] == tree and b["percent"] == 5 for b in hp)


async def test_capstone_requires_level_850(make_client, make_character) -> None:  # type: ignore[no-untyped-def]
    u = await make_client()
    cid = await make_character(u.user_id, level=849, base_class_id=await _class_id("warrior"))
    ver = (await u.http.get(f"/api/v1/characters/{cid}/talents")).json()["version"]
    tree = "warrior_defense"
    plan = {
        f"{tree}_n1": 5,
        f"{tree}_n2": 3,
        f"{tree}_n3": 5,
        f"{tree}_n4": 3,
        f"{tree}_n5": 5,
        f"{tree}_n7": 2,
        f"{tree}_n9": 1,
        "living_fortress": 1,
    }
    r = await u.http.post(f"/api/v1/characters/{cid}/talents", json={"allocations": plan, "expected_version": ver})
    assert r.status_code == 422 and "level_locked" in [d["code"] for d in r.json()["error"]["details"]]


async def test_talent_reset_costs(make_client, make_character) -> None:  # type: ignore[no-untyped-def]
    u = await make_client()
    low = await make_character(u.user_id, level=200, base_class_id=await _class_id("mage"))
    v = (await u.http.get(f"/api/v1/characters/{low}/talents")).json()
    await u.http.post(
        f"/api/v1/characters/{low}/talents",
        json={"allocations": {"mage_arcane_n1": 3}, "expected_version": v["version"]},
    )
    r = await u.http.post(f"/api/v1/characters/{low}/talents/reset", headers={"Idempotency-Key": uuid.uuid4().hex})
    assert r.status_code == 200 and r.json()["gold"] == 0 and r.json()["refunded_points"] == 3
    high = await make_character(u.user_id, level=700, base_class_id=await _class_id("mage"))
    v2 = (await u.http.get(f"/api/v1/characters/{high}/talents")).json()
    await u.http.post(
        f"/api/v1/characters/{high}/talents",
        json={"allocations": {"mage_arcane_n1": 5}, "expected_version": v2["version"]},
    )
    r2 = await u.http.post(f"/api/v1/characters/{high}/talents/reset", headers={"Idempotency-Key": uuid.uuid4().hex})
    assert r2.status_code == 409 and r2.json()["error"]["code"] in ("material_system_unavailable", "insufficient_funds")


async def test_abilities_and_awakening(make_client, make_character) -> None:  # type: ignore[no-untyped-def]
    u = await make_client()
    cid = await make_character(u.user_id, level=650, base_class_id=await _class_id("warrior"))
    await u.http.post(f"/api/v1/characters/{cid}/class/promote", json={"branch_code": "reaver"})
    await u.http.post(f"/api/v1/characters/{cid}/class/specialize", json={"specialization_code": "berserker"})
    r = (await u.http.get(f"/api/v1/characters/{cid}/abilities", params={"locale": "es"})).json()
    names = {a["code"]: a for a in r["abilities"]}
    assert names["whirlwind"]["name"] == "Torbellino" and names["titans_wrath"]["type"] == "ULTIMATE"
    assert r["awakening"]["code"] == "red_feast" and r["awakening"]["active"] is True
    assert r["awakening"]["name"] == "Festín rojo"


async def test_admin_publish_validation_for_talents_and_abilities(make_client) -> None:  # type: ignore[no-untyped-def]
    gd = await make_client("game_designer")
    suffix = uuid.uuid4().hex[:6]
    node = {
        "tree_code": "warrior_defense",
        "tier": 1,
        "slot": "x",
        "max_rank": 1,
        "required_points_in_tree": 0,
        "required_level": 1,
        "is_capstone": False,
        "requires": [],
        "archetype_key": None,
        "effects": [{"effect_type": "STAT_FLAT", "params": {"stat": "STR", "amount": 1}}],
    }
    a, b = f"cyc_a_{suffix}", f"cyc_b_{suffix}"
    await gd.http.post("/api/v1/admin/content/talent_node", json={"code": a, "data": {**node, "requires": [b]}})
    await gd.http.post("/api/v1/admin/content/talent_node", json={"code": b, "data": {**node, "requires": [a]}})
    v = (await gd.http.post(f"/api/v1/admin/content/talent_node/{a}/validate")).json()
    assert "circular_dependency" in [i["code"] for i in v["issues"]]
    dup = f"dup_cap_{suffix}"
    await gd.http.post(
        "/api/v1/admin/content/talent_node",
        json={
            "code": dup,
            "data": {**node, "tier": 6, "is_capstone": True, "required_points_in_tree": 24, "required_level": 850},
        },
    )
    v2 = (await gd.http.post(f"/api/v1/admin/content/talent_node/{dup}/validate")).json()
    assert "duplicate_capstone" in [i["code"] for i in v2["issues"]]
    bad = f"bad_eff_{suffix}"
    await gd.http.post(
        "/api/v1/admin/content/talent_node",
        json={
            "code": bad,
            "data": {**node, "effects": [{"effect_type": "STAT_FLAT", "params": {"stat": "STR", "amount": "lots"}}]},
        },
    )
    v3 = (await gd.http.post(f"/api/v1/admin/content/talent_node/{bad}/validate")).json()
    assert v3["issues"][0]["code"] == "invalid_effect"
    extra = f"sixth_active_{suffix}"
    await gd.http.post(
        "/api/v1/admin/content/ability",
        json={
            "code": extra,
            "data": {
                "owner_type": "class",
                "owner_code": "warrior",
                "ability_type": "ACTIVE",
                "unlock_level": 10,
                "target_rule": "enemy_single",
                "tags": [],
                "ranks": [{"rank": 1, "effects": [{"effect_type": "DAMAGE", "params": {"percent_of_power": 100}}]}],
            },
        },
    )
    v4 = (await gd.http.post(f"/api/v1/admin/content/ability/{extra}/validate")).json()
    assert "too_many_actives" in [i["code"] for i in v4["issues"]]
    for code, t in (
        (a, "talent_node"),
        (b, "talent_node"),
        (dup, "talent_node"),
        (bad, "talent_node"),
        (extra, "ability"),
    ):
        await gd.http.delete(f"/api/v1/admin/content/{t}/{code}")


async def test_all_class_content_fully_localized(make_client) -> None:  # type: ignore[no-untyped-def]
    t = await make_client("translator")
    for ns in ("class", "branch", "spec", "passive", "ability", "talent", "awakening", "mastery", "resource"):
        c = (await t.http.get("/api/v1/admin/localization/completeness", params={"namespace": ns})).json()
        for loc in ("en", "tr", "zh-CN", "es"):
            assert c[loc]["missing"] == 0, (ns, loc)
