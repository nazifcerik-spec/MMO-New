"""Phase 14: item domain — tier gates, budgets, validators, deterministic rolls, provenance, revision pinning."""

import uuid

from sqlalchemy import select

from app.content.loader import load_yaml
from app.db.session import get_sessionmaker
from app.game_engine.items import ItemRules, distributable_budget, requirement_problems, suggested_requirements
from app.models.character import Character
from app.models.items import ItemInstance, ItemProvenance
from app.services import items, progression
from tests.test_classes import _class_id

RULES = ItemRules.model_validate(load_yaml("balance/item_rules.yaml")["data"])
ADMIN = "/api/v1/admin/content"


def _key() -> str:
    return f"k-{uuid.uuid4().hex}"


def test_canonical_tier_gates_budgets_and_profiles() -> None:
    assert [(t.min_level, t.max_level) for t in RULES.tiers] == [
        (1, 49), (50, 99), (100, 199), (200, 299), (300, 399), (400, 499),
        (500, 599), (600, 699), (700, 849), (850, 949), (950, 1000),
    ]  # fmt: skip
    b = RULES.rarity_budgets
    assert [(b[r].min, b[r].max) for r in ("common", "fine", "rare", "epic", "legendary", "mythic")] == [
        (0, 1), (1, 2), (2, 3), (3, 4), (4, 5), (5, 6),
    ]  # fmt: skip
    assert b["legendary"].unique_required and b["mythic"].mastery_scaling_required and b["relic"].fixed
    assert suggested_requirements(RULES, "heavy_weapon", 600) == {"STR": 470, "VIT": 140}
    assert suggested_requirements(RULES, "cloth_armor", 600) == {"INT": 390, "SPI": 160}


def test_requirement_budget_thresholds() -> None:
    budget = distributable_budget(RULES, 100)  # 35 + 99*3
    assert budget == 332
    assert requirement_problems(RULES, 100, {"STR": 150}) == []
    assert requirement_problems(RULES, 100, {"STR": 150, "VIT": 60})[0][0] == "warning"  # 63%
    assert requirement_problems(RULES, 100, {"STR": 180, "VIT": 60})[0][0] == "error"  # 72%
    assert any(p[0] == "error" for p in requirement_problems(RULES, 10, {"STR": 40}))  # unreachable single stat


async def _hero(make_client, make_character, level=150, cls="warrior"):  # type: ignore[no-untyped-def]
    staff = await make_client("admin")
    u = await make_client()
    cid = await make_character(u.user_id, level=level, base_class_id=await _class_id(cls))
    return staff, u, cid


async def _grant(staff, cid, code, seed=None, key=None, qty=1):  # type: ignore[no-untyped-def]
    body = {"template_code": code, "reason": "test", "quantity": qty, **({"seed": seed} if seed is not None else {})}
    return await staff.http.post(
        f"/api/v1/admin/characters/{cid}/items", json=body, headers={"Idempotency-Key": key or _key()}
    )


async def test_grant_is_deterministic_idempotent_and_logged(make_client, make_character) -> None:  # type: ignore[no-untyped-def]
    staff, u, cid = await _hero(make_client, make_character)
    a = (await _grant(staff, cid, "ironwall_helm", seed=42)).json()
    b = (await _grant(staff, cid, "ironwall_helm", seed=42)).json()
    assert a["id"] != b["id"] and a["affixes"] == b["affixes"] and 2 <= len(a["affixes"]) <= 3
    assert len({x["code"] for x in a["affixes"]}) == len(a["affixes"])
    key = _key()
    first = (await _grant(staff, cid, "militia_axe", key=key)).json()
    again = (await _grant(staff, cid, "militia_axe", key=key)).json()
    assert first["id"] == again["id"]
    async with get_sessionmaker()() as db:
        prov = (await db.execute(select(ItemProvenance).where(ItemProvenance.instance_id == a["id"]))).scalar_one()
        assert prov.event == "created" and prov.details["seed"] == 42 and prov.details["revision_no"] == 1
    mats = (await _grant(staff, cid, "copper_ore", qty=50)).json()
    assert mats["quantity"] == 50 and mats["affixes"] == []
    assert (await _grant(staff, cid, "ironwall_helm", qty=2)).status_code == 422
    player = await make_client()
    assert (await _grant(player, cid, "copper_ore")).status_code == 403
    listed = (await u.http.get(f"/api/v1/characters/{cid}/items")).json()["items"]
    assert len(listed) == 4
    assert (await (await make_client()).http.get(f"/api/v1/characters/{cid}/items")).status_code == 404


async def test_roll_budgets_across_seeds(make_client) -> None:  # type: ignore[no-untyped-def]
    staff = await make_client("admin")
    for code, lo, hi in (
        ("ironwall_helm", 2, 3),
        ("shadowsilk_hood", 3, 4),
        ("bulwark_of_dawn", 4, 5),
        ("starfall_scepter", 5, 6),
    ):
        rolls = (
            await staff.http.post(f"/api/v1/admin/items/{code}/roll-preview", json={"seeds": list(range(20))})
        ).json()["rolls"]
        for r in rolls:
            groups = [a["code"] for a in r["affixes"]]
            assert lo <= len(groups) <= hi, (code, r)
            assert sum(a["code"] == "vanguards" for a in r["affixes"]) <= 1
    relic = (
        await staff.http.post("/api/v1/admin/items/crown_of_the_last_emperor/roll-preview", json={"seeds": [1]})
    ).json()
    assert [a["kind"] for a in relic["rolls"][0]["affixes"]] == ["fixed", "fixed"]
    assert (
        await (await make_client()).http.post("/api/v1/admin/items/ironwall_helm/roll-preview", json={"seeds": [1]})
    ).status_code == 403


async def test_new_revision_never_reinterprets_existing_instances(make_client, make_character) -> None:  # type: ignore[no-untyped-def]
    staff, u, cid = await _hero(make_client, make_character)
    old = (await _grant(staff, cid, "militia_axe", seed=7)).json()
    view = (await staff.http.get(f"{ADMIN}/item_template/militia_axe")).json()
    data = {**view["data"], "base_stats": [{"stat": "attack_power", "amount": 999}]}
    upd = await staff.http.put(
        f"{ADMIN}/item_template/militia_axe", json={"data": data, "expected_version": view["edit_version"]}
    )
    assert upd.status_code == 200, upd.text
    pub = await staff.http.post(
        f"{ADMIN}/releases", json={"items": [{"entity_type": "item_template", "code": "militia_axe"}]}
    )
    assert pub.status_code == 200, pub.text
    new = (await _grant(staff, cid, "militia_axe", seed=7)).json()
    old_again = (await u.http.get(f"/api/v1/characters/{cid}/items/{old['id']}")).json()

    def flat(v: dict) -> list[dict]:  # type: ignore[type-arg]
        return [
            e for e in v["effects"] if e["params"].get("stat") == "attack_power" and e["effect_type"] == "STAT_FLAT"
        ]

    assert old_again["template_revision_no"] == 1 and flat(old_again)[0]["params"]["amount"] == 55
    assert new["template_revision_no"] == 2 and flat(new)[0]["params"]["amount"] == 999


async def test_requirements_and_equipment_effects_with_set_bonus(make_client, make_character) -> None:  # type: ignore[no-untyped-def]
    staff, u, cid = await _hero(make_client, make_character, level=150)
    helm = (await _grant(staff, cid, "ironwall_helm", seed=1)).json()
    detail = (await u.http.get(f"/api/v1/characters/{cid}/items/{helm['id']}")).json()
    assert not detail["equippable"] and {x["kind"] for x in detail["unmet"]} == {"stat"}  # no stats allocated
    low = await make_client()
    lid = await make_character(low.user_id, level=5, base_class_id=await _class_id("mage"))
    staff2 = staff
    wand = (await _grant(staff2, lid, "starfall_scepter", seed=1)).json()
    unmet = (await low.http.get(f"/api/v1/characters/{lid}/items/{wand['id']}")).json()["unmet"]
    assert {"level", "stat"} <= {x["kind"] for x in unmet}
    chest = (await _grant(staff, cid, "ironwall_chestplate", seed=2)).json()
    async with get_sessionmaker()() as db:
        ch = await db.get(Character, cid)
        assert ch is not None
        before = (await progression.stat_sheet(db, ch)).finals()
        for iid, slot in ((helm["id"], "head"), (chest["id"], "chest")):
            inst = await db.get(ItemInstance, iid)
            assert inst is not None
            inst.location, inst.equipped_slot = "equipped", slot
        await db.commit()
        after = (await progression.stat_sheet(db, ch)).finals()
        effects = await items.equipment_effects(db, ch)
        assert after["armor"] > before["armor"] + 240
        assert any(e["effect_type"] == "STAT_PERCENT" and e["params"]["stat"] == "armor" for e in effects)  # 2-piece
        assert not any(e["effect_type"] == "DAMAGE_REDUCTION" and e["params"].get("percent") == 4 for e in effects)
        inst = await db.get(ItemInstance, helm["id"])
        assert inst is not None
        inst.durability = 0  # broken gear is inert
        await db.commit()
        broken = (await progression.stat_sheet(db, ch)).finals()
        assert broken["armor"] < after["armor"]


async def _issues(staff, data) -> set[str]:  # type: ignore[no-untyped-def]
    code = f"t_{uuid.uuid4().hex[:10]}"
    r = await staff.http.post(f"{ADMIN}/item_template", json={"code": code, "data": data})
    assert r.status_code == 201, r.text
    v = (await staff.http.post(f"{ADMIN}/item_template/{code}/validate")).json()
    return {i["code"] for i in v["issues"]}


def _tpl(**over):  # type: ignore[no-untyped-def]
    base = {
        "category": "weapon", "slot": "main_hand", "weapon_family": "sword", "tier": 2, "min_level": 120,
        "rarity": "rare", "durability": {"max": 50}, "affix_rules": {"pool": ["of_strength", "brutal"]},
    }  # fmt: skip
    return {**base, **over}


async def test_template_publish_validators(make_client) -> None:  # type: ignore[no-untyped-def]
    staff = await make_client("item_editor")
    assert await _issues(staff, _tpl()) == set()
    assert "tier_level_mismatch" in await _issues(staff, _tpl(min_level=20))
    assert "unique_required" in await _issues(staff, _tpl(rarity="legendary", tier=6, min_level=520))
    mythic = _tpl(
        rarity="mythic",
        tier=9,
        min_level=860,
        unique_effect={"key": "x", "effects": [{"effect_type": "STAT_FLAT", "params": {"stat": "STR", "amount": 1}}]},
    )
    assert "mastery_scaling_required" in await _issues(staff, mythic)
    assert "relic_random_affixes" in await _issues(
        staff, _tpl(rarity="relic", tier=10, min_level=990, unique_effect=mythic["unique_effect"])
    )
    assert "affix_budget" in await _issues(staff, _tpl(affix_rules={"pool": ["of_strength"], "max": 5}))
    assert "not_stackable" in await _issues(staff, _tpl(stack_size=20))
    assert "slot_not_allowed" in await _issues(staff, _tpl(slot="head"))
    assert "missing_family" in await _issues(staff, _tpl(weapon_family=None))
    assert "unknown_reference" in await _issues(staff, _tpl(affix_rules={"pool": ["nope_affix"]}))
    assert "requirement_budget" in await _issues(staff, _tpl(requirements={"stats": {"STR": 250, "VIT": 100}}))
    assert "affixes_not_allowed" in await _issues(
        staff,
        {
            "category": "material",
            "tier": 0,
            "min_level": 1,
            "rarity": "common",
            "stack_size": 99,
            "affix_rules": {"pool": ["keen"]},
        },
    )
    bad_schema = await staff.http.post(
        f"{ADMIN}/item_template", json={"code": "t_bad_stat", "data": _tpl(base_stats=[{"stat": "MANA", "amount": 1}])}
    )
    assert bad_schema.status_code == 422
    player = await make_client()
    assert (await player.http.post(f"{ADMIN}/item_template", json={"code": "t_x", "data": _tpl()})).status_code == 403


async def test_catalog_is_localized_and_paginated(make_client) -> None:  # type: ignore[no-untyped-def]
    c = await make_client()
    page = (await c.http.get("/api/v1/items/templates", params={"limit": 5})).json()
    assert len(page["items"]) == 5 and page["next_after_id"] and page["total_published"] >= 16
    tr = (await c.http.get("/api/v1/items/templates/bulwark_of_dawn", headers={"Accept-Language": "tr"})).json()
    assert tr["name"] == "Şafak Siperi" and tr["unique_effect"]["key"] == "dawn_aegis"
    helm = (await c.http.get("/api/v1/items/templates/ironwall_helm")).json()
    assert helm["set"]["code"] == "ironwall_regalia" and len(helm["set"]["bonuses"]) == 2
    weapons = (await c.http.get("/api/v1/items/templates", params={"category": "weapon", "limit": 50})).json()["items"]
    assert weapons and all(w["category"] == "weapon" for w in weapons)
