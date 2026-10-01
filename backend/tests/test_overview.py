"""Phase 23: shell summary, next meaningful goals, activity feed and the readable preview log."""

import uuid
from datetime import timedelta

from app.db.session import get_sessionmaker
from app.models.character import Character
from app.services import goals
from tests.test_afk import Clock, _start
from tests.test_afk import _hero as afk_hero


def _key() -> str:
    return f"k-{uuid.uuid4().hex}"


async def test_summary_and_next_goals(make_client, make_character) -> None:  # type: ignore[no-untyped-def]
    u = await make_client()
    cid = await make_character(u.user_id, level=95, unspent=12)
    s = (await u.http.get(f"/api/v1/characters/{cid}/summary")).json()
    assert s["level"] == 95 and s["gold"] == 0 and s["afk"] is None and s["title"]["kind"] == "level"
    kinds = [g["kind"] for g in s["next_goals"]]
    assert kinds[0] == "stat_points" and "talent_points" in kinds
    levels = [g["level"] for g in s["next_goals"] if "level" in g and g["kind"] != "profession_rank"]
    assert levels == sorted(levels) and {"level_title", "class_stage"} & set(kinds)
    other = await make_client()
    assert (await other.http.get(f"/api/v1/characters/{cid}/summary")).status_code == 404


async def test_activity_feed_aggregates_records(make_client, make_character, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from app.services import afk

    clock = Clock()
    monkeypatch.setattr(afk, "now_utc", clock)
    u, cid = await afk_hero(make_client, make_character)
    assert (await _start(u, cid, duration=600)).status_code == 201
    s = (await u.http.get(f"/api/v1/characters/{cid}/summary")).json()
    assert s["afk"]["zone_code"] == "whispering_meadows"
    clock.now += timedelta(minutes=11)
    assert (
        await u.http.post(f"/api/v1/characters/{cid}/afk/claim", headers={"Idempotency-Key": _key()})
    ).status_code == 200
    async with get_sessionmaker()() as db:
        ch = await db.get(Character, cid)
        assert ch is not None
        await goals.bump(db, ch, add={"kills": 100})
        await db.commit()
    feed = (await u.http.get(f"/api/v1/characters/{cid}/activity")).json()
    types = [f["type"] for f in feed]
    assert "afk_claimed" in types and "achievement" in types
    assert [f["at"] for f in feed] == sorted((f["at"] for f in feed), reverse=True)
    afk_row = next(f for f in feed if f["type"] == "afk_claimed")
    assert afk_row["zone_code"] == "whispering_meadows" and afk_row["kills"] >= 0


async def test_preview_includes_structured_sample_log(make_client, make_character) -> None:  # type: ignore[no-untyped-def]
    u, cid = await afk_hero(make_client, make_character)
    r = await u.http.post(f"/api/v1/characters/{cid}/combat/preview", json={"fights": 3})
    assert r.status_code == 200, r.text
    log = r.json()["sample_log"]
    assert (0 < len(log["events"]) <= 80 and log["events"][-1]["event_type"] in ("END", "HIT", "CRIT", "DEATH")) or len(
        log["events"]
    ) == 80
    assert any(a["side"] == "players" for a in log["actors"].values())
    assert {e["event_type"] for e in log["events"]} & {"HIT", "CRIT", "BLOCK", "DODGE"}
