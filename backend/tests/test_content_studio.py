"""Phase 24: Content Studio — modules, dependency graph, delete/archive protection, review workflow, bundles,
localization dashboard and export/import."""

import uuid

import pytest

from app.core.config import get_settings
from app.services.content import references

ADMIN = "/api/v1/admin/content"
L10N = "/api/v1/admin/localization"


def _code(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def test_reference_extraction_is_field_driven() -> None:
    data = {
        "weapon_family": "sword",
        "affix_rules": {"pool": ["keen", "group:offense"]},
        "salvage": [{"template_code": "copper_ore"}],
        "entries": [{"kind": "material", "ref": "silverleaf"}, {"kind": "gold"}],
        "prerequisites": ["first_steps"],
        "objectives": [{"kind": "explore", "zone": "whispering_meadows"}],
    }
    assert references.extract(data) == {
        ("weapon_family", "sword"), ("affix", "keen"), ("item_template", "copper_ore"),
        ("item_template", "silverleaf"), ("quest", "first_steps"), ("zone", "whispering_meadows"),
    }  # fmt: skip


async def test_modules_and_dependency_graph(make_client) -> None:  # type: ignore[no-untyped-def]
    gd = await make_client("game_designer")
    mods = {m["module"]: m for m in (await gd.http.get(f"{ADMIN}/modules")).json()}
    assert {
        "races",
        "classes",
        "skills",
        "talents",
        "professions",
        "world",
        "drops",
        "crafting",
        "quests",
        "achievements",
        "balance",
    } <= set(mods)
    race = next(t for t in mods["races"]["types"] if t["entity_type"] == "race")
    assert race["counts"]["published"] == 8 and race["can_publish"]
    refs = (await gd.http.get(f"{ADMIN}/quest/first_steps/references")).json()
    assert refs["by_type"].get("quest", 0) >= 1 and any(i["code"] == "into_the_meadows" for i in refs["items"])
    zone = (await gd.http.get(f"{ADMIN}/zone/whispering_meadows/references")).json()
    assert (zone["total"] >= 1 and {"entity_type": "drop_table", "code": "meadow_drops"} in zone["outgoing"]) or zone[
        "outgoing"
    ]
    player = await make_client()
    assert (await player.http.get(f"{ADMIN}/modules")).status_code == 403


async def test_referenced_content_cannot_be_deleted_or_silently_archived(make_client) -> None:  # type: ignore[no-untyped-def]
    gd = await make_client("game_designer")
    base = {"quest_type": "kill", "objectives": [{"kind": "kill", "count": 1}]}
    a, b = _code("dep_a"), _code("dep_b")
    assert (await gd.http.post(f"{ADMIN}/quest", json={"code": a, "data": base})).status_code == 201
    assert (
        await gd.http.post(f"{ADMIN}/quest", json={"code": b, "data": {**base, "prerequisites": [a]}})
    ).status_code == 201
    blocked = await gd.http.delete(f"{ADMIN}/quest/{a}")
    assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "referenced"
    assert blocked.json()["error"]["details"]["by_type"] == {"quest": 1}
    assert (await gd.http.delete(f"{ADMIN}/quest/{b}")).status_code == 204
    assert (await gd.http.delete(f"{ADMIN}/quest/{a}")).status_code == 204
    arch = await gd.http.post(f"{ADMIN}/quest/first_steps/status", json={"status": "archived"})
    assert arch.json()["error"]["code"] == "referenced"


async def test_review_workflow_four_eyes_and_bundle_publish(make_client, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(get_settings(), "content_review_required", True)
    author = await make_client("game_designer")
    reviewer = await make_client("game_designer")
    base = {"quest_type": "kill", "objectives": [{"kind": "kill", "count": 3}]}
    q1, q2 = _code("bun_a"), _code("bun_b")
    await author.http.post(f"{ADMIN}/quest", json={"code": q1, "data": base})
    await author.http.post(f"{ADMIN}/quest", json={"code": q2, "data": {**base, "prerequisites": [q1]}})
    wf = (await author.http.get(f"{ADMIN}/quest/{q1}/workflow")).json()
    assert wf["stage"] == "draft" and wf["review_required"]
    bundle = {
        "items": [{"entity_type": "quest", "code": q1}, {"entity_type": "quest", "code": q2}],
        "label": "quest chain",
    }
    early = await author.http.post(f"{ADMIN}/releases", json=bundle)
    assert early.json()["error"]["code"] == "review_required"
    for q in (q1, q2):
        assert (await author.http.post(f"{ADMIN}/quest/{q}/review/request")).json()["stage"] == "review"
        assert (await author.http.post(f"{ADMIN}/quest/{q}/review/approve", json={})).status_code == 403  # four eyes
    rej = await reviewer.http.post(f"{ADMIN}/quest/{q2}/review/reject", json={"note": "count too low"})
    assert rej.json()["stage"] == "draft" and rej.json()["review"]["note"] == "count too low"
    await author.http.post(f"{ADMIN}/quest/{q2}/review/request")
    for q in (q1, q2):
        assert (await reviewer.http.post(f"{ADMIN}/quest/{q}/review/approve", json={"note": "ok"})).json()[
            "stage"
        ] == "approved"
    pub = await author.http.post(f"{ADMIN}/releases", json=bundle)
    assert pub.status_code == 200, pub.text
    rel = pub.json()["release_version"]
    hist = (await author.http.get(f"{ADMIN}/quest/{q2}/history")).json()
    assert hist[0]["release_version"] == rel  # both in one release revision
    assert (await author.http.get(f"{ADMIN}/quest/{q1}/workflow")).json()["stage"] == "published"
    # editing again makes the approval stale
    cur = (await author.http.get(f"{ADMIN}/quest/{q1}")).json()
    await author.http.put(
        f"{ADMIN}/quest/{q1}", json={"data": {**base, "min_level": 5}, "expected_version": cur["edit_version"]}
    )
    assert (await author.http.get(f"{ADMIN}/quest/{q1}/workflow")).json()["stage"] == "draft"


async def test_localization_dashboard_export_import(make_client) -> None:  # type: ignore[no-untyped-def]
    tr = await make_client("translator")
    dash = (await tr.http.get(f"{L10N}/dashboard", params={"namespace": "quest"})).json()
    assert set(dash["locales"]) == {"en", "tr", "zh-CN", "es"} and dash["locales"]["en"]["present_pct"] == 100.0
    assert any(n["namespace"] == "quest" for n in (await tr.http.get(f"{L10N}/namespaces")).json())
    exp = (await tr.http.get(f"{L10N}/export", params={"namespace": "quest"})).json()
    row = next(r for r in exp["rows"] if r["key"] == "quest.first_steps.name" and r["locale"] == "es")
    csv = await tr.http.get(f"{L10N}/export", params={"namespace": "quest", "format": "csv"})
    assert csv.headers["content-type"].startswith("text/csv") and "quest.first_steps.name" in csv.text
    rows = [
        {"key": "quest.first_steps.name", "locale": "es", "value": "Primeros pasitos", "status": "reviewed"},
        {"key": "quest.first_steps.name", "locale": "en", "value": "Changed EN", "status": "draft"},
        {"key": "no.such.key", "locale": "tr", "value": "x"},
    ]
    dry = (await tr.http.post(f"{L10N}/import", json={"rows": rows, "dry_run": True})).json()
    assert dry["skipped_reviewed"] == 1 and dry["unknown_key"] == 1 and dry["updated"] == 1
    assert (await tr.http.get(f"{L10N}/export", params={"namespace": "quest"})).json() == exp  # dry run wrote nothing
    real = (await tr.http.post(f"{L10N}/import", json={"rows": rows, "dry_run": False})).json()
    assert real["updated"] == 1 and not real["errors"]
    after = {
        (r["key"], r["locale"]): r
        for r in (await tr.http.get(f"{L10N}/export", params={"namespace": "quest"})).json()["rows"]
    }
    assert after[("quest.first_steps.name", "es")]["value"] == "Primeros pasitos"
    assert after[("quest.first_steps.name", "es")]["status"] == "reviewed"  # translator may review
    assert after[("quest.first_steps.name", "en")]["status"] == "published"  # reviewed EN never overwritten
    assert row["status"] in ("draft", "reviewed", "published")
    ed = await make_client("item_editor")
    assert (await ed.http.post(f"{L10N}/import", json={"rows": rows, "overwrite_reviewed": True})).status_code == 403


@pytest.fixture(autouse=True)
def _reset_review_setting():  # type: ignore[no-untyped-def]
    yield
    get_settings().content_review_required = False
