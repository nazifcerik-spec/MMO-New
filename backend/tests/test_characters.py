from httpx import AsyncClient


async def test_character_endpoints_require_auth(client: AsyncClient) -> None:
    assert (await client.get("/api/v1/characters")).status_code == 401
    assert (
        await client.post("/api/v1/characters", json={"name": "Arven", "race_id": 1, "base_class_id": 1})
    ).status_code == 401


async def test_character_options_are_content_driven(client: AsyncClient) -> None:
    r = await client.get("/api/v1/content/character-options")
    assert r.status_code == 200
    assert set(r.json()) == {"races", "base_classes"}


async def test_name_check(make_client) -> None:  # type: ignore[no-untyped-def]
    u = await make_client()
    ok = await u.http.get("/api/v1/characters/name-check", params={"name": "Arvenwise"})
    assert ok.json() == {"name": "Arvenwise", "available": True, "valid": True, "error_code": None}
    bad = await u.http.get("/api/v1/characters/name-check", params={"name": "Admin"})
    assert bad.json()["valid"] is False and bad.json()["error_code"] == "reserved_name"


async def test_other_users_character_is_not_found(make_client) -> None:  # type: ignore[no-untyped-def]
    u = await make_client()
    assert (await u.http.get("/api/v1/characters/999999")).status_code == 404
    assert (await u.http.get("/api/v1/characters")).json() == []
