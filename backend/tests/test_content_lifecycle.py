import uuid

import pytest
from pydantic import BaseModel, ConfigDict, Field

from app.services.content.types.balance import BALANCE_SCHEMAS


class _TestCfg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: int = Field(ge=0, le=100)


@pytest.fixture(autouse=True)
def _register_test_schema():
    BALANCE_SCHEMAS["test_cfg_schema"] = _TestCfg
    yield


def _code() -> str:
    return f"test_cfg_{uuid.uuid4().hex[:8]}"


async def _create(http, code: str, value: int = 1) -> dict:
    BALANCE_SCHEMAS[code] = _TestCfg
    r = await http.post("/api/v1/admin/content/balance_config", json={"code": code, "data": {"data": {"value": value}}})
    assert r.status_code == 201, r.text
    return r.json()


async def test_rbac_on_content_endpoints(make_client) -> None:  # type: ignore[no-untyped-def]
    player = await make_client()
    assert (await player.http.get("/api/v1/admin/content/balance_config")).status_code == 403
    editor = await make_client("item_editor")  # can read drafts but lacks balance.edit
    assert (await editor.http.get("/api/v1/admin/content/balance_config")).status_code == 200
    r = await editor.http.post("/api/v1/admin/content/balance_config", json={"code": _code(), "data": {"data": {}}})
    assert r.status_code == 403
    assert (await editor.http.get("/api/v1/admin/content/nope_type")).status_code == 404


async def test_full_lifecycle_draft_publish_history_diff_rollback(make_client) -> None:  # type: ignore[no-untyped-def]
    gd = await make_client("game_designer")
    code = _code()
    created = await _create(gd.http, code, 10)
    assert created["status"] == "draft" and created["revision_no"] == 0 and created["has_pending_changes"]

    rel = await gd.http.post(
        "/api/v1/admin/content/releases",
        json={"items": [{"entity_type": "balance_config", "code": code}], "label": "first"},
    )
    assert rel.status_code == 200
    first_release = rel.json()["release_version"]

    view = (await gd.http.get(f"/api/v1/admin/content/balance_config/{code}")).json()
    assert view["status"] == "published" and view["revision_no"] == 1 and view["edit_version"] == 0

    # Edit a published entity: goes to a pending draft; live data unchanged.
    upd = await gd.http.put(
        f"/api/v1/admin/content/balance_config/{code}", json={"data": {"data": {"value": 20}}, "expected_version": 0}
    )
    assert upd.status_code == 200
    assert upd.json()["data"]["data"]["value"] == 20 and upd.json()["live_data"]["data"]["value"] == 10
    # Concurrent editor with stale token -> 409 with current data for diff.
    stale = await gd.http.put(
        f"/api/v1/admin/content/balance_config/{code}", json={"data": {"data": {"value": 30}}, "expected_version": 0}
    )
    assert stale.status_code == 409 and stale.json()["error"]["details"]["current_data"]["data"]["value"] == 20

    pub2 = await gd.http.post(
        "/api/v1/admin/content/releases", json={"items": [{"entity_type": "balance_config", "code": code}]}
    )
    assert pub2.json()["release_version"] > first_release

    hist = (await gd.http.get(f"/api/v1/admin/content/balance_config/{code}/history")).json()
    assert [h["revision_no"] for h in hist] == [2, 1]
    d = (
        await gd.http.get(f"/api/v1/admin/content/balance_config/{code}/diff", params={"from_rev": 1, "to_rev": 2})
    ).json()
    assert d == [{"path": "data.data.value", "from": 10, "to": 20}]

    rb = await gd.http.post(f"/api/v1/admin/content/balance_config/{code}/rollback", json={"revision_no": 1})
    assert rb.status_code == 200
    r3 = (await gd.http.get(f"/api/v1/admin/content/balance_config/{code}/revisions/3")).json()
    r1 = (await gd.http.get(f"/api/v1/admin/content/balance_config/{code}/revisions/1")).json()
    assert r3["data"]["data"] == r1["data"]["data"]  # rollback = new revision with old data
    assert r3["data_hash"] == r1["data_hash"]

    audit = await gd.http.get("/api/v1/admin/audit", params={"entity_type": "balance_config", "entity_id": code})
    assert audit.status_code == 200  # game_designer has audit.view
    actions = {a["action"] for a in audit.json()["items"]}
    assert {"content.create", "content.update", "content.publish"} <= actions


async def test_publish_blocked_by_validation(make_client) -> None:  # type: ignore[no-untyped-def]
    gd = await make_client("game_designer")
    code = _code()
    r = await gd.http.post("/api/v1/admin/content/balance_config", json={"code": code, "data": {"data": {"value": 5}}})
    assert r.status_code == 201  # no schema registered for this code -> blocked at publish
    blocked = await gd.http.post(
        "/api/v1/admin/content/releases", json={"items": [{"entity_type": "balance_config", "code": code}]}
    )
    assert blocked.status_code == 422 and blocked.json()["error"]["code"] == "publish_blocked"
    code2 = _code()
    await _create(gd.http, code2, 1)
    bad = await gd.http.put(
        f"/api/v1/admin/content/balance_config/{code2}", json={"data": {"data": {"value": 999}}, "expected_version": 1}
    )
    assert bad.status_code == 200  # stored as draft...
    v = (await gd.http.post(f"/api/v1/admin/content/balance_config/{code2}/validate")).json()
    assert v["ok"] is False  # ...but validation reports the schema error


async def test_publish_bundle_is_atomic(make_client) -> None:  # type: ignore[no-untyped-def]
    gd = await make_client("game_designer")
    good, bad = _code(), _code()
    await _create(gd.http, good, 1)
    await gd.http.post("/api/v1/admin/content/balance_config", json={"code": bad, "data": {"data": {"value": 1}}})
    r = await gd.http.post(
        "/api/v1/admin/content/releases",
        json={
            "items": [{"entity_type": "balance_config", "code": good}, {"entity_type": "balance_config", "code": bad}]
        },
    )
    assert r.status_code == 422
    view = (await gd.http.get(f"/api/v1/admin/content/balance_config/{good}")).json()
    assert view["status"] == "draft"  # nothing from the failed bundle was published


async def test_status_changes_and_code_rules(make_client) -> None:  # type: ignore[no-untyped-def]
    gd = await make_client("game_designer")
    code = _code()
    await _create(gd.http, code)
    assert (
        await gd.http.post(f"/api/v1/admin/content/balance_config/{code}/status", json={"status": "disabled"})
    ).status_code == 409  # never published
    await gd.http.post(
        "/api/v1/admin/content/releases", json={"items": [{"entity_type": "balance_config", "code": code}]}
    )
    arch = await gd.http.post(f"/api/v1/admin/content/balance_config/{code}/status", json={"status": "archived"})
    assert arch.json()["status"] == "archived"
    ro = await gd.http.put(
        f"/api/v1/admin/content/balance_config/{code}", json={"data": {"data": {"value": 2}}, "expected_version": 0}
    )
    assert ro.status_code == 409 and ro.json()["error"]["code"] == "archived"
    assert (await gd.http.delete(f"/api/v1/admin/content/balance_config/{code}")).status_code == 409
    dup = await gd.http.post("/api/v1/admin/content/balance_config", json={"code": code, "data": {"data": {}}})
    assert dup.status_code == 409
    badcode = await gd.http.post(
        "/api/v1/admin/content/balance_config", json={"code": "Bad Code!", "data": {"data": {}}}
    )
    assert badcode.status_code == 422


async def test_seeded_afk_config_is_canonical(make_client) -> None:  # type: ignore[no-untyped-def]
    gd = await make_client("game_designer")
    view = (await gd.http.get("/api/v1/admin/content/balance_config/afk")).json()
    data = view["data"]["data"]
    assert data["max_session_seconds"] == 10800
    assert [(b["from_hours"], b["to_hours"], b["percent"]) for b in data["daily_efficiency_bands"]] == [
        (0, 9, 100),
        (9, 12, 80),
        (12, 18, 50),
        (18, 24, 25),
    ]
    assert view["issues"] == []
    reg = (await gd.http.get("/api/v1/admin/content/effects/registry")).json()
    assert len(reg) >= 17


async def test_public_content_version(client) -> None:  # type: ignore[no-untyped-def]
    r = await client.get("/api/v1/content/version")
    assert r.status_code == 200 and r.json()["release_version"] >= 1
