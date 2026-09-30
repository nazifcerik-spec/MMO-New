from httpx import AsyncClient


async def test_admin_endpoints_deny_anonymous_and_players(make_client, client: AsyncClient) -> None:  # type: ignore[no-untyped-def]
    assert (await client.get("/api/v1/admin/localization/keys")).status_code == 401
    player = await make_client()
    for path in ("/api/v1/admin/localization/keys", "/api/v1/admin/users", "/api/v1/admin/audit"):
        r = await player.http.get(path)
        assert r.status_code == 403, path


async def test_translator_can_edit_but_not_manage_users(make_client) -> None:  # type: ignore[no-untyped-def]
    t = await make_client("translator")
    r = await t.http.get("/api/v1/admin/localization/keys", params={"namespace": "stat", "limit": 5})
    assert r.status_code == 200 and r.json()["total"] >= 60
    item = r.json()["items"][0]
    tr = item["values"]["tr"]
    upd = await t.http.put(
        f"/api/v1/admin/localization/keys/{item['key']}/tr",
        json={"value": tr["value"], "status": "reviewed", "expected_version": tr["version"]},
    )
    assert upd.status_code == 200 and upd.json()["version"] == tr["version"] + 1
    stale = await t.http.put(
        f"/api/v1/admin/localization/keys/{item['key']}/tr",
        json={"value": "x", "status": "draft", "expected_version": tr["version"]},
    )
    assert stale.status_code == 409 and stale.json()["error"]["details"]["current_version"] == tr["version"] + 1
    assert (await t.http.get("/api/v1/admin/users")).status_code == 403


async def test_item_editor_cannot_review_translations(make_client) -> None:  # type: ignore[no-untyped-def]
    e = await make_client("item_editor")
    r = await e.http.put(
        "/api/v1/admin/localization/keys/stat.str.name/es", json={"value": "Fuerza", "status": "published"}
    )
    assert r.status_code == 403


async def test_missing_locale_filter_and_completeness(make_client) -> None:  # type: ignore[no-untyped-def]
    t = await make_client("translator")
    r = await t.http.get("/api/v1/admin/localization/keys", params={"namespace": "stat", "missing_locale": "tr"})
    assert r.status_code == 200 and r.json()["total"] == 0
    c = await t.http.get("/api/v1/admin/localization/completeness", params={"namespace": "stat"})
    assert c.json()["zh-CN"]["missing"] == 0


async def test_role_grant_rank_guard_and_audit(make_client) -> None:  # type: ignore[no-untyped-def]
    admin = await make_client("admin")
    target = await make_client()
    ok = await admin.http.post(f"/api/v1/admin/users/{target.user_id}/roles", json={"role": "translator"})
    assert ok.status_code == 204
    esc = await admin.http.post(f"/api/v1/admin/users/{target.user_id}/roles", json={"role": "superadmin"})
    assert esc.status_code == 403 and esc.json()["error"]["code"] == "rank_too_low"
    same = await admin.http.post(f"/api/v1/admin/users/{admin.user_id}/roles", json={"role": "admin"})
    assert same.status_code == 403
    me = await target.http.get("/api/v1/auth/me")
    assert "translator" in me.json()["roles"] and me.json()["is_staff"] is True
    audit = await admin.http.get(
        "/api/v1/admin/audit", params={"entity_type": "user", "entity_id": str(target.user_id)}
    )
    assert any(a["action"] == "role.grant" and a["actor_user_id"] == admin.user_id for a in audit.json()["items"])
    rv = await admin.http.delete(f"/api/v1/admin/users/{target.user_id}/roles/player")
    assert rv.status_code == 403
