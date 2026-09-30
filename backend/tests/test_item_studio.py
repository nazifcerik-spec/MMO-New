"""Phase 15: Admin Item Studio API."""

import json
import uuid

ADMIN = "/api/v1/admin"


def _code(prefix: str = "st") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _tpl(**over):  # type: ignore[no-untyped-def]
    base = {
        "category": "weapon", "slot": "main_hand", "weapon_family": "sword", "tier": 2, "min_level": 120,
        "rarity": "rare", "durability": {"max": 50}, "affix_rules": {"pool": ["of_strength", "brutal"]},
        "base_stats": [{"stat": "attack_power", "amount": 100}],
    }  # fmt: skip
    return {**base, **over}


GEN = {
    "category": "weapon", "slot": "main_hand", "weapon_family": "sword", "tier_from": 1, "tier_to": 3,
    "rarity_weights": {"fine": 1, "rare": 2}, "requirement_profile": "heavy_weapon", "count": 6,
    "code_pattern": "{theme}_{family}_t{tier}_{n}",
    "name_patterns": {"en": "{theme} {family} {n}", "tr": "{theme} {family} {n}"},
    "theme": {"code": "gx", "names": {"en": "Gx", "tr": "Gx"}}, "affix_pool": ["of_strength", "brutal", "keen"],
    "class_tags": ["slayer"], "salvage_material": "iron_ingot",
}  # fmt: skip


async def test_rbac_matrix(make_client) -> None:  # type: ignore[no-untyped-def]
    player, translator, editor = await make_client(), await make_client("translator"), await make_client("item_editor")
    assert (await player.http.get(f"{ADMIN}/items")).status_code == 403
    assert (await translator.http.get(f"{ADMIN}/items")).status_code == 200
    assert (await translator.http.post(f"{ADMIN}/items/generator", json={"params": GEN})).status_code == 403
    assert (await editor.http.post(f"{ADMIN}/items/generator", json={"params": GEN})).status_code == 200
    # item_editor may create drafts but not publish
    code = _code()
    assert (
        await editor.http.post(f"{ADMIN}/content/item_template", json={"code": code, "data": _tpl()})
    ).status_code == 201
    pub = await editor.http.post(
        f"{ADMIN}/content/releases", json={"items": [{"entity_type": "item_template", "code": code}]}
    )
    assert pub.status_code == 403
    gd = await make_client("game_designer")
    pub = await gd.http.post(
        f"{ADMIN}/content/releases", json={"items": [{"entity_type": "item_template", "code": code}]}
    )
    assert pub.status_code == 200, pub.text
    assert (
        await editor.http.post(
            f"{ADMIN}/items/bulk-translation-status", json={"codes": [code], "locale": "tr", "status": "reviewed"}
        )
    ).status_code == 403


async def test_list_filters_search_sort_and_translation_state(make_client) -> None:  # type: ignore[no-untyped-def]
    gd = await make_client("game_designer")
    r = (await gd.http.get(f"{ADMIN}/items", params={"category": "armor", "sort": "min_level", "order": "desc"})).json()
    levels = [i["min_level"] for i in r["items"]]
    assert (
        r["total"] >= 5 and levels == sorted(levels, reverse=True) and all(i["category"] == "armor" for i in r["items"])
    )
    by_name = (await gd.http.get(f"{ADMIN}/items", params={"q": "şafak"})).json()["items"]
    assert [i["code"] for i in by_name] == ["bulwark_of_dawn"]
    assert (await gd.http.get(f"{ADMIN}/items", params={"q": "ironwall", "tier": 2})).json()["total"] == 3
    complete = (await gd.http.get(f"{ADMIN}/items", params={"translation": "complete"})).json()["total"]
    code = _code()
    await gd.http.post(f"{ADMIN}/content/item_template", json={"code": code, "data": _tpl()})
    incomplete = (await gd.http.get(f"{ADMIN}/items", params={"translation": "incomplete", "q": code})).json()
    assert incomplete["total"] == 1 and incomplete["items"][0]["translations"]["zh-CN"] == "missing"
    assert (await gd.http.get(f"{ADMIN}/items", params={"translation": "complete"})).json()["total"] == complete
    assert (await gd.http.get(f"{ADMIN}/items", params={"class_tag": "vanguard"})).json()["total"] >= 0
    assert (await gd.http.get(f"{ADMIN}/items", params={"sort": "drop table"})).status_code == 422


async def test_inspector_edit_conflict_clone_archive_rollback(make_client) -> None:  # type: ignore[no-untyped-def]
    gd = await make_client("game_designer")
    ins = (await gd.http.get(f"{ADMIN}/items/ironwall_helm")).json()
    assert ins["texts"]["name"]["tr"]["value"] == "Demirsur Miğferi"
    assert ins["requirement_budget"]["percent"] < ins["requirement_budget"]["warn_pct"]
    assert {d["code"] for d in ins["references"]["drop_tables"]} >= {"ironroot_forest_drops"}
    code = _code("cl")
    cl = await gd.http.post(f"{ADMIN}/items/ironwall_helm/clone", json={"new_code": code})
    assert cl.status_code == 201 and cl.json()["status"] == "draft"
    assert (await gd.http.get(f"{ADMIN}/items/{code}")).json()["texts"]["name"]["tr"]["value"] == "Demirsur Miğferi"
    assert (await gd.http.post(f"{ADMIN}/items/ironwall_helm/clone", json={"new_code": code})).status_code == 409
    # concurrent edit: two editors, same base version
    v = ins["edit_version"]
    a = await gd.http.put(
        f"{ADMIN}/content/item_template/ironwall_helm",
        json={"data": {**ins["data"], "vendor_value": 1}, "expected_version": v},
    )
    b = await gd.http.put(
        f"{ADMIN}/content/item_template/ironwall_helm",
        json={"data": {**ins["data"], "vendor_value": 2}, "expected_version": v},
    )
    assert a.status_code == 200 and b.status_code == 409
    assert b.json()["error"]["details"]["current_data"]["vendor_value"] == 1  # UI shows diff against this
    # invalid effect schema is rejected at validation
    bad = {**ins["data"], "effects": [{"effect_type": "DAMAGE", "params": {"percent_of_power": 99999}}]}
    await gd.http.put(
        f"{ADMIN}/content/item_template/ironwall_helm", json={"data": bad, "expected_version": a.json()["edit_version"]}
    )
    val = (await gd.http.post(f"{ADMIN}/content/item_template/ironwall_helm/validate")).json()
    assert not val["ok"] and "invalid_effect" in {i["code"] for i in val["issues"]}
    # archive + rollback-as-new-revision on a fresh item
    code2 = _code("ar")
    await gd.http.post(f"{ADMIN}/content/item_template", json={"code": code2, "data": _tpl()})
    await gd.http.post(f"{ADMIN}/content/releases", json={"items": [{"entity_type": "item_template", "code": code2}]})
    view = (await gd.http.get(f"{ADMIN}/content/item_template/{code2}")).json()
    await gd.http.put(
        f"{ADMIN}/content/item_template/{code2}",
        json={"data": {**view["data"], "vendor_value": 77}, "expected_version": view["edit_version"]},
    )
    await gd.http.post(f"{ADMIN}/content/releases", json={"items": [{"entity_type": "item_template", "code": code2}]})
    rb = await gd.http.post(f"{ADMIN}/content/item_template/{code2}/rollback", json={"revision_no": 1})
    assert rb.status_code == 200, rb.text
    hist = (await gd.http.get(f"{ADMIN}/content/item_template/{code2}/history")).json()
    assert len(hist) == 3
    arch = await gd.http.post(f"{ADMIN}/content/item_template/{code2}/status", json={"status": "archived"})
    assert arch.status_code == 200
    assert (await gd.http.get(f"{ADMIN}/items", params={"status": "archived", "q": code2})).json()["total"] == 1
    cmp = (await gd.http.get(f"{ADMIN}/items/compare", params={"a": "ironwall_helm", "b": "ironwall_greaves"})).json()
    assert any(d["path"] == "slot" for d in cmp["diff"])


async def test_translation_fallback_and_bulk_status(make_client) -> None:  # type: ignore[no-untyped-def]
    gd = await make_client("game_designer")
    code = _code("tl")
    await gd.http.post(f"{ADMIN}/content/item_template", json={"code": code, "data": _tpl()})
    await gd.http.put(
        f"{ADMIN}/items/{code}/texts/name/en",
        json={"value": "Fallback Blade", "status": "draft", "expected_version": 0},
    )
    await gd.http.post(f"{ADMIN}/content/releases", json={"items": [{"entity_type": "item_template", "code": code}]})
    zh = (await gd.http.get(f"/api/v1/items/templates/{code}", headers={"Accept-Language": "zh-CN"})).json()
    assert zh["name"] == "Fallback Blade"  # zh-CN missing -> en
    await gd.http.put(
        f"{ADMIN}/items/{code}/texts/name/tr",
        json={"value": "Yedek Kılıç", "status": "draft", "expected_version": 0},
    )
    n = (
        await gd.http.post(
            f"{ADMIN}/items/bulk-translation-status", json={"codes": [code], "locale": "tr", "status": "reviewed"}
        )
    ).json()
    assert n["changed"] == 1
    ins = (await gd.http.get(f"{ADMIN}/items/{code}")).json()
    assert ins["texts"]["name"]["tr"]["status"] == "reviewed"
    translator = await make_client("translator")
    r = await translator.http.post(
        f"{ADMIN}/items/bulk-translation-status", json={"codes": [code], "locale": "tr", "status": "draft"}
    )
    assert r.status_code == 200


async def test_bulk_edit_safe_fields_only(make_client) -> None:  # type: ignore[no-untyped-def]
    gd = await make_client("game_designer")
    codes = [_code("bk"), _code("bk")]
    versions = {}
    for c in codes:
        versions[c] = (await gd.http.post(f"{ADMIN}/content/item_template", json={"code": c, "data": _tpl()})).json()[
            "edit_version"
        ]
    ok = await gd.http.post(
        f"{ADMIN}/items/bulk-edit",
        json={"codes": codes, "patch": {"vendor_value": 9, "tradeable": False}, "expected_versions": versions},
    )
    assert ok.status_code == 200, ok.text
    unsafe = await gd.http.post(
        f"{ADMIN}/items/bulk-edit", json={"codes": codes, "patch": {"rarity": "mythic"}, "expected_versions": versions}
    )
    assert unsafe.status_code == 422 and unsafe.json()["error"]["code"] == "unsafe_bulk_field"
    stale = await gd.http.post(
        f"{ADMIN}/items/bulk-edit", json={"codes": codes, "patch": {"vendor_value": 1}, "expected_versions": versions}
    )
    assert stale.status_code == 409  # all-or-nothing on version conflict
    view = (await gd.http.get(f"{ADMIN}/content/item_template/{codes[0]}")).json()
    assert view["data"]["vendor_value"] == 9 and view["data"]["tradeable"] is False


async def test_export_import_roundtrip_with_dry_run(make_client) -> None:  # type: ignore[no-untyped-def]
    gd = await make_client("game_designer")
    exp = await gd.http.get(f"{ADMIN}/items/export", params={"q": "ironwall_chest", "format": "csv"})
    assert exp.status_code == 200 and exp.headers["content-type"].startswith("text/csv")
    csv_text = exp.text
    assert "ironwall_chestplate" in csv_text and "Demirsur" in csv_text
    dry = (
        await gd.http.post(f"{ADMIN}/items/import", json={"format": "csv", "content": csv_text, "dry_run": True})
    ).json()
    assert dry["summary"]["updates"] == 1 and dry["summary"]["errors"] == 0 and not dry["summary"]["committed"]
    rows = json.loads((await gd.http.get(f"{ADMIN}/items/export", params={"q": "militia_axe"})).text)
    new_code = _code("im")
    rows.append({"code": new_code, "data": _tpl(), "l10n": {"name": {"en": "Imported", "tr": "İçe Aktarılan"}}})
    rows.append({"code": new_code, "data": _tpl()})  # duplicate in file
    rows.append({"code": _code("im"), "data": _tpl(rarity="legendary", tier=6, min_level=520)})  # validator error
    report = (
        await gd.http.post(
            f"{ADMIN}/items/import", json={"format": "json", "content": json.dumps(rows), "dry_run": False}
        )
    ).json()
    codes = {i["code"] for e in report["report"] for i in e["issues"] if i["level"] == "error"}
    assert {"duplicate_code", "unique_required"} <= codes and not report["summary"]["committed"]
    assert (await gd.http.get(f"{ADMIN}/items", params={"q": new_code})).json()["total"] == 0  # atomic: nothing written
    good = [rows[0], {"code": new_code, "data": _tpl(), "l10n": {"name": {"en": "Imported"}}}]
    ok = (
        await gd.http.post(
            f"{ADMIN}/items/import", json={"format": "json", "content": json.dumps(good), "dry_run": False}
        )
    ).json()
    assert ok["summary"]["committed"] and ok["summary"]["creates"] == 1
    stale = await gd.http.post(
        f"{ADMIN}/items/import", json={"format": "json", "content": json.dumps(good[:1]), "dry_run": True}
    )
    assert "version_conflict" in {i["code"] for e in stale.json()["report"] for i in e["issues"]}


async def test_generator_dry_run_commit_and_duplicate_prevention(make_client) -> None:  # type: ignore[no-untyped-def]
    ed = await make_client("item_editor")
    params = {**GEN, "theme": {"code": f"g{uuid.uuid4().hex[:5]}", "names": {"en": "Gale", "tr": "Bora"}}}
    dry = (await ed.http.post(f"{ADMIN}/items/generator", json={"params": params})).json()
    s = dry["summary"]
    assert s["count"] == 6 and s["errors"] == 0 and not s["committed"], dry
    assert {r["tier"] for r in dry["rows"]} == {1, 2, 3} and [r["rarity"] for r in dry["rows"]].count("rare") == 4
    assert all(r["name"].startswith("Gale Sword") for r in dry["rows"])
    first = dry["rows"][0]["code"]
    assert (await ed.http.get(f"{ADMIN}/items", params={"q": first})).json()["total"] == 0  # dry-run wrote nothing
    done = (await ed.http.post(f"{ADMIN}/items/generator", json={"params": params, "commit": True})).json()
    assert done["summary"]["committed"]
    created = (await ed.http.get(f"{ADMIN}/items", params={"q": params["theme"]["code"]})).json()
    assert created["total"] == 6 and all(i["status"] == "draft" for i in created["items"])
    again = (await ed.http.post(f"{ADMIN}/items/generator", json={"params": params})).json()
    assert again["summary"]["errors"] == 6 and "duplicate_code" in {i["code"] for i in again["rows"][0]["issues"]}
    blocked = await ed.http.post(f"{ADMIN}/items/generator", json={"params": params, "commit": True})
    assert blocked.status_code == 422 and blocked.json()["error"]["code"] == "generator_invalid"
    bad = await ed.http.post(f"{ADMIN}/items/generator", json={"params": {**params, "code_pattern": "{theme}; drop"}})
    assert bad.status_code == 422
    legendary = {
        **params,
        "theme": {"code": "lg", "names": {"en": "L"}},
        "tier_from": 6,
        "tier_to": 6,
        "rarity_weights": {"legendary": 1},
        "count": 2,
    }
    lg = (await ed.http.post(f"{ADMIN}/items/generator", json={"params": legendary})).json()
    assert "unique_required" in {i["code"] for r in lg["rows"] for i in r["issues"]}


async def test_preview_on_test_characters(make_client) -> None:  # type: ignore[no-untyped-def]
    gd = await make_client("game_designer")
    profiles = (await gd.http.get(f"{ADMIN}/items/preview-profiles")).json()
    assert {"warrior_600", "mage_850"} <= {p["code"] for p in profiles}
    w = (await gd.http.post(f"{ADMIN}/items/militia_axe/preview", json={"profile": "warrior_600"})).json()
    assert w["requirements_met"] and w["deltas"]["attack_power"] > 0
    m = (await gd.http.post(f"{ADMIN}/items/crown_of_the_last_emperor/preview", json={"profile": "warrior_100"})).json()
    assert not m["requirements_met"] and {"level"} <= {u["kind"] for u in m["unmet"]}
    after = (await gd.http.get(f"{ADMIN}/items", params={"q": "zzzz"})).json()
    assert after["total"] == 0
