"""Phase 13: AFK session lifecycle — snapshot immutability, 3h cap, exactly-once claim, bands, replay, sweeper."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.db.session import get_sessionmaker
from app.models.afk import AfkDailyUsage, AfkSession
from app.models.progression import EconomyLedger
from app.services import afk
from tests.test_classes import _class_id


class Clock:
    def __init__(self) -> None:
        self.now = datetime.now(UTC).replace(microsecond=0)

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def clock(monkeypatch):  # type: ignore[no-untyped-def]
    c = Clock()
    monkeypatch.setattr(afk, "now_utc", c)
    return c


def _key() -> str:
    return f"k-{uuid.uuid4().hex}"


async def _hero(make_client, make_character, level: int = 30, cls: str = "paladin"):  # type: ignore[no-untyped-def]
    u = await make_client()
    cid = await make_character(u.user_id, level=level, unspent=(level - 1) * 3, base_class_id=await _class_id(cls))
    prog = (await u.http.get(f"/api/v1/characters/{cid}/progression")).json()
    r = await u.http.post(
        f"/api/v1/characters/{cid}/stats/auto",
        json={
            "profile_code": "hybrid_support" if cls == "paladin" else "physical_dps",
            "expected_version": prog["version"],
        },
        headers={"Idempotency-Key": _key()},
    )
    assert r.status_code == 200, r.text
    return u, cid


async def _start(u, cid, duration=3 * 3600, zone="whispering_meadows", key=None, **extra):  # type: ignore[no-untyped-def]
    return await u.http.post(
        f"/api/v1/characters/{cid}/afk/start",
        json={"zone_code": zone, "duration_s": duration, **extra},
        headers={"Idempotency-Key": key or _key()},
    )


async def _claim(u, cid, key=None):  # type: ignore[no-untyped-def]
    return await u.http.post(f"/api/v1/characters/{cid}/afk/claim", headers={"Idempotency-Key": key or _key()})


async def test_start_validation_cap_and_single_active(make_client, make_character, clock) -> None:  # type: ignore[no-untyped-def]
    u, cid = await _hero(make_client, make_character)
    assert (await _start(u, cid, duration=3 * 3600 + 1)).status_code == 422
    assert (await _start(u, cid, duration=30)).status_code == 422
    assert (await _start(u, cid, zone="ironroot_forest")).json()["error"]["code"] == "zone_locked"
    key = _key()
    first = await _start(u, cid, key=key)
    assert first.status_code == 201, first.text
    s = first.json()
    assert s["status"] == "running" and s["remaining_s"] == 3 * 3600 and not s["claimable"]
    assert s["build"]["class"] == "paladin" and s["efficiency"][0]["percent"] == 100
    assert (await _start(u, cid, key=key)).json()["id"] == s["id"]  # idempotent start
    again = await _start(u, cid)
    assert again.status_code == 409 and again.json()["error"]["code"] == "afk_session_active"
    early = await _claim(u, cid)
    assert early.status_code == 409 and early.json()["error"]["code"] == "afk_not_finished"
    other = await make_client()
    assert (await other.http.get(f"/api/v1/characters/{cid}/afk")).status_code == 404


async def test_claim_grants_once_with_signals(make_client, make_character, clock) -> None:  # type: ignore[no-untyped-def]
    u, cid = await _hero(make_client, make_character)
    before = (await u.http.get(f"/api/v1/characters/{cid}/progression")).json()
    sid = (await _start(u, cid)).json()["id"]
    clock.now += timedelta(hours=3, seconds=1)
    cur = (await u.http.get(f"/api/v1/characters/{cid}/afk")).json()["session"]
    assert cur["claimable"] and cur["remaining_s"] == 0
    key = _key()
    r = await _claim(u, cid, key)
    assert r.status_code == 200, r.text
    out = r.json()
    res = out["result"]
    assert res["elapsed_s"] == 3 * 3600 and res["fights"] > 50 and res["xp"] > 0 and out["gold"] > 0
    assert out["signals"] and {s["kind"] for s in out["signals"]} >= {"xp_progress", "pity_progress"}
    assert out["loot_pending"] == res["drops"]
    after = (await u.http.get(f"/api/v1/characters/{cid}/progression")).json()
    assert (after["level"], after["xp"]) != (before["level"], before["xp"])
    replay = await _claim(u, cid, key)
    assert replay.json()["replayed"] and replay.json()["result"] == res
    second = await _claim(u, cid)
    assert second.status_code == 404 and second.json()["error"]["code"] == "afk_no_session"
    async with get_sessionmaker()() as db:
        gold = (await db.execute(select(EconomyLedger).where(EconomyLedger.character_id == cid))).scalars().all()
        assert len(gold) == 1 and gold[0].delta == out["gold"] and gold[0].reason == "afk_reward"
    hist = (await u.http.get(f"/api/v1/characters/{cid}/afk/history")).json()["items"]
    assert [h["session_id"] for h in hist] == [sid]


async def test_concurrent_claims_grant_exactly_once(make_client, make_character, clock) -> None:  # type: ignore[no-untyped-def]
    u, cid = await _hero(make_client, make_character)
    await _start(u, cid, duration=1800)
    clock.now += timedelta(minutes=31)
    results = await asyncio.gather(*[_claim(u, cid) for _ in range(4)])
    codes = sorted(r.status_code for r in results)
    assert codes.count(200) == 1 and all(c in (200, 404, 409) for c in codes), [r.text for r in results]
    async with get_sessionmaker()() as db:
        n = (await db.execute(select(EconomyLedger).where(EconomyLedger.character_id == cid))).scalars().all()
        assert len(n) <= 1


async def test_mid_session_build_change_does_not_affect_result(make_client, make_character, clock) -> None:  # type: ignore[no-untyped-def]
    u, cid = await _hero(make_client, make_character, level=30, cls="warrior")
    s = (await _start(u, cid, duration=3600)).json()
    snap_stats = s["player_stats"]
    prof = (await u.http.get(f"/api/v1/characters/{cid}/afk-profile")).json()["profile"]
    await u.http.put(
        f"/api/v1/characters/{cid}/afk-profile",
        json={
            "expected_version": prof["version"],
            "stance": "aggressive",
            "risk_level": "dangerous",
            "mode": "PASSIVE_ONLY",
        },
    )
    async with get_sessionmaker()() as db:
        from app.models.character import Character

        ch = await db.get(Character, cid)
        assert ch is not None
        ch.level = 45  # e.g. XP from another source mid-session
        await db.commit()
    cur = (await u.http.get(f"/api/v1/characters/{cid}/afk")).json()["session"]
    assert cur["player_stats"] == snap_stats and cur["build"] == s["build"]
    assert cur["risk_level"] == "balanced"
    clock.now += timedelta(hours=1)
    out = (await _claim(u, cid)).json()
    gd = await make_client("game_designer")
    rep = (await gd.http.post(f"/api/v1/admin/afk/{out['session_id']}/replay")).json()
    assert rep["match"] and rep["snapshot_hash_ok"]
    assert (await u.http.post(f"/api/v1/admin/afk/{out['session_id']}/replay")).status_code == 403


async def test_daily_band_crossing_and_true_up_on_early_stop(make_client, make_character, clock) -> None:  # type: ignore[no-untyped-def]
    u, cid = await _hero(make_client, make_character)
    clock.now = clock.now.replace(hour=10, minute=0, second=0)
    day = clock.now.date()
    async with get_sessionmaker()() as db:
        from app.models.character import Character

        uid = (await db.get(Character, cid)).user_id  # type: ignore[union-attr]
        db.add(AfkDailyUsage(user_id=uid, day=day, seconds=8 * 3600))
        await db.commit()
    s = (await _start(u, cid)).json()
    assert [(e["to_s"] - e["from_s"], e["percent"]) for e in s["efficiency"]] == [(3600, 100), (7200, 80)]
    clock.now += timedelta(minutes=90)
    stopped = (await u.http.post(f"/api/v1/characters/{cid}/afk/stop")).json()
    assert stopped["claimable"] and stopped["elapsed_s"] == 5400
    out = (await _claim(u, cid)).json()
    assert out["result"]["elapsed_s"] == 5400
    assert 80 < out["result"]["avg_efficiency_pct"] < 100
    async with get_sessionmaker()() as db:
        usage = (await db.execute(select(AfkDailyUsage).where(AfkDailyUsage.user_id == uid))).scalar_one()
        assert usage.seconds == 8 * 3600 + 5400


async def test_same_snapshot_and_seed_is_deterministic(make_client, make_character, clock) -> None:  # type: ignore[no-untyped-def]
    u, cid = await _hero(make_client, make_character)
    sid = (await _start(u, cid, duration=2 * 3600)).json()["id"]
    async with get_sessionmaker()() as db:
        row = await db.get(AfkSession, sid)
        assert row is not None
        a = afk._resolve_sync(row.snapshot, row.seed, 7200)
        b = afk._resolve_sync(row.snapshot, row.seed, 7200)
        c = afk._resolve_sync(row.snapshot, row.seed + 1, 7200)
        half = afk._resolve_sync(row.snapshot, row.seed, 3600)
    assert a == b and a["hash"] != c["hash"]
    assert half["xp"] < a["xp"] and half["fights"] < a["fights"]
    assert a["timeline"] and len(a["timeline"]) == 4


async def test_sweeper_pre_resolves_and_claim_uses_stored_result(make_client, make_character, clock) -> None:  # type: ignore[no-untyped-def]
    u, cid = await _hero(make_client, make_character)
    sid = (await _start(u, cid, duration=600)).json()["id"]
    clock.now += timedelta(minutes=11)
    async with get_sessionmaker()() as db:
        n = await afk.sweep(db, now=clock.now)
        await db.commit()
        row = await db.get(AfkSession, sid)
        assert n >= 1 and row is not None and row.status == "resolved"
        stored = row.result_hash
    out = (await _claim(u, cid)).json()
    async with get_sessionmaker()() as db:
        row = await db.get(AfkSession, sid)
        assert row is not None and row.status == "claimed" and row.result_hash == stored
    assert out["session_id"] == sid
    player = await make_client()
    assert (await player.http.post("/api/v1/admin/afk/sweep")).status_code == 403


async def test_deaths_cost_efficiency_not_progress(make_client, make_character, clock) -> None:  # type: ignore[no-untyped-def]
    u, cid = await _hero(make_client, make_character, level=5, cls="warrior")
    await _start(u, cid, duration=3600, risk_level="elite_hunt")
    clock.now += timedelta(hours=1)
    res = (await _claim(u, cid)).json()["result"]
    if res["deaths"]:
        assert res["durability_loss_pct"] > 0 and res["xp"] >= 0 and res["gold"] >= 0
    assert res["fights"] >= res["wins"] + res["deaths"] - 1
