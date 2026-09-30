import asyncio
import uuid

from app.db.session import get_sessionmaker
from app.models.character import Character
from app.services import progression


def _key() -> str:
    return uuid.uuid4().hex


async def test_progression_view_and_localized_labels(make_client, make_character) -> None:  # type: ignore[no-untyped-def]
    u = await make_client()
    cid = await make_character(u.user_id, level=1)
    r = await u.http.get(f"/api/v1/characters/{cid}/progression", params={"locale": "tr"})
    assert r.status_code == 200
    v = r.json()
    assert v["level"] == 1 and v["title_code"] == "novice" and v["next_breakpoint"] == 100
    assert v["labels"]["title.level.novice.name"] == "Acemi"
    assert v["labels"]["stat.max_hp.name"] == "Maks. Can"
    assert v["stats"]["primary"]["STR"]["final"] == 5 + 5  # base + warrior class bonus


async def test_allocate_validation_and_success(make_client, make_character) -> None:  # type: ignore[no-untyped-def]
    u = await make_client()
    cid = await make_character(u.user_id, unspent=10)
    ver = (await u.http.get(f"/api/v1/characters/{cid}/progression")).json()["version"]
    url = f"/api/v1/characters/{cid}/stats/allocate"
    bad = [
        ({"STR": 11}, "insufficient_points"),
        ({"CHA": 1}, "invalid_stat"),
        ({"STR": -1}, "invalid_amount"),
        ({"STR": 0}, "empty_allocation"),
    ]
    for pts, code in bad:
        r = await u.http.post(url, json={"points": pts, "expected_version": ver}, headers={"Idempotency-Key": _key()})
        assert r.status_code == 422 and r.json()["error"]["code"] == code, pts
    assert (await u.http.post(url, json={"points": {"STR": 1}, "expected_version": ver})).status_code == 422
    key = _key()
    ok = await u.http.post(
        url, json={"points": {"STR": 6, "VIT": 4}, "expected_version": ver}, headers={"Idempotency-Key": key}
    )
    assert ok.status_code == 200 and ok.json()["unspent_stat_points"] == 0
    again = await u.http.post(
        url, json={"points": {"STR": 6, "VIT": 4}, "expected_version": ver}, headers={"Idempotency-Key": key}
    )
    assert again.status_code == 200 and again.json()["allocation"]["STR"] == 6  # replay, not double-spend
    stale = await u.http.post(
        url, json={"points": {"STR": 1}, "expected_version": ver}, headers={"Idempotency-Key": _key()}
    )
    assert stale.status_code == 409
    view = (await u.http.get(f"/api/v1/characters/{cid}/progression")).json()
    assert view["stats"]["primary"]["STR"]["raw"] == 5 + 5 + 6  # base + class + allocated


async def test_admin_xp_grant_multi_level_idempotent(make_client, make_character) -> None:  # type: ignore[no-untyped-def]
    admin = await make_client("admin")
    player = await make_client()
    cid = await make_character(player.user_id)
    async with get_sessionmaker()() as s:
        cfg = await progression.load_config(s)
    amount = sum(cfg.xp_table[1:100]) + 10
    key = _key()
    url = f"/api/v1/admin/characters/{cid}/xp"
    r = await admin.http.post(url, json={"amount": amount, "reason": "test grant"}, headers={"Idempotency-Key": key})
    assert r.status_code == 200 and r.json()["level_after"] == 100 and r.json()["stat_points_gained"] == 297
    assert r.json()["breakpoints_crossed"] == [100]
    r2 = await admin.http.post(url, json={"amount": amount, "reason": "test grant"}, headers={"Idempotency-Key": key})
    assert r2.json()["replayed"] is True
    view = (await player.http.get(f"/api/v1/characters/{cid}/progression")).json()
    assert view["level"] == 100 and view["xp"] == 10 and view["unspent_stat_points"] == 297
    assert view["title_code"] == "veteran"
    assert (
        await player.http.post(url, json={"amount": 5, "reason": "cheat"}, headers={"Idempotency-Key": _key()})
    ).status_code == 403


async def test_concurrent_xp_grants_same_key_apply_once(make_client, make_character) -> None:  # type: ignore[no-untyped-def]
    player = await make_client()
    cid = await make_character(player.user_id)
    key = _key()

    async def grant() -> dict:
        from sqlalchemy import select
        from sqlalchemy.exc import IntegrityError

        async with get_sessionmaker()() as s:
            ch = (await s.execute(select(Character).where(Character.id == cid).with_for_update())).scalar_one()
            try:
                res = await progression.grant_xp(s, character=ch, amount=100, idempotency_key=key, source_type="test")
                await s.commit()
                return res
            except IntegrityError:
                await s.rollback()
                return {"replayed": True}

    results = await asyncio.gather(*(grant() for _ in range(5)))
    assert sum(1 for r in results if not r["replayed"]) == 1
    async with get_sessionmaker()() as s:
        ch = await s.get(Character, cid)
        assert ch is not None and (ch.level, ch.xp) == (2, 100 - 48)  # applied exactly once


async def test_respec_free_early_and_costly_later(make_client, make_character) -> None:  # type: ignore[no-untyped-def]
    u = await make_client()
    cid = await make_character(u.user_id, level=50, unspent=20)
    ver = (await u.http.get(f"/api/v1/characters/{cid}/progression")).json()["version"]
    await u.http.post(
        f"/api/v1/characters/{cid}/stats/allocate",
        json={"points": {"INT": 20}, "expected_version": ver},
        headers={"Idempotency-Key": _key()},
    )
    q = (await u.http.get(f"/api/v1/characters/{cid}/stats/respec-quote")).json()
    assert q["points_refunded"] == 20 and q["gold_cost"] == 0
    r = await u.http.post(f"/api/v1/characters/{cid}/stats/respec", headers={"Idempotency-Key": _key()})
    assert r.status_code == 200 and r.json()["unspent_after"] == 20

    from tests.test_races import _race_id

    cid2 = await make_character(u.user_id, level=700, unspent=10, race_id=await _race_id("orc"))
    ver2 = (await u.http.get(f"/api/v1/characters/{cid2}/progression")).json()["version"]
    await u.http.post(
        f"/api/v1/characters/{cid2}/stats/allocate",
        json={"points": {"INT": 10}, "expected_version": ver2},
        headers={"Idempotency-Key": _key()},
    )
    q2 = (await u.http.get(f"/api/v1/characters/{cid2}/stats/respec-quote")).json()
    assert q2["gold_cost"] == 1200
    broke = await u.http.post(f"/api/v1/characters/{cid2}/stats/respec", headers={"Idempotency-Key": _key()})
    assert broke.status_code == 409 and broke.json()["error"]["code"] == "insufficient_funds"


async def test_stat_profiles_listed_localized(client) -> None:  # type: ignore[no-untyped-def]
    r = await client.get("/api/v1/content/stat-profiles", params={"locale": "zh-CN"})
    codes = {p["code"]: p for p in r.json()}
    assert set(codes) == {"tank", "physical_dps", "caster_dps", "healer", "hybrid_support"}
    assert codes["healer"]["name"] == "治疗"


async def test_template_allocation_preview(make_client, make_character) -> None:  # type: ignore[no-untyped-def]
    u = await make_client()
    cid = await make_character(u.user_id, unspent=20)
    ver = (await u.http.get(f"/api/v1/characters/{cid}/progression")).json()["version"]
    r = await u.http.post(
        f"/api/v1/characters/{cid}/stats/auto",
        json={"profile_code": "healer", "preview": True, "expected_version": ver},
        headers={"Idempotency-Key": _key()},
    )
    assert r.status_code == 200 and sum(r.json()["plan"].values()) == 20 and r.json()["plan"]["WIS"] == 9
