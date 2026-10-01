"""Phase 22: quest graph + promotion gates, aggregated achievements, titles (status rarity), collections, prestige."""

import uuid

from sqlalchemy import select

from app.content.loader import load_yaml
from app.db.session import get_sessionmaker
from app.game_engine import goals as rules
from app.models.character import Character
from app.models.quests import CharacterQuest
from app.services import goals
from tests.test_afk import Clock, _start
from tests.test_afk import _hero as afk_hero
from tests.test_classes import _class_id
from tests.test_inventory import _grant

CFG = rules.GoalsConfig.model_validate(load_yaml("balance/goals.yaml")["data"])
ADMIN = "/api/v1/admin/content"


def _key() -> str:
    return f"k-{uuid.uuid4().hex}"


def Q(cid: int) -> str:
    return f"/api/v1/characters/{cid}/quests"


def test_rules_graph_progress_rarity_prestige() -> None:
    assert rules.find_cycle({"a": ("b",), "b": ("c",), "c": ("a",)}) is not None
    assert rules.find_cycle({"a": (), "b": ("a",), "c": ("a", "b")}) is None
    objs = [
        {"kind": "kill", "zone": "z1", "count": 10},
        {"kind": "level", "level": 50},
        {"kind": "action", "action": "trade", "count": 2},
    ]
    p = rules.apply_event(objs, [], "afk_claimed", {"zone_code": "z2", "kills": 99})
    assert p == [0, 0, 0]
    p = rules.apply_event(objs, p, "afk_claimed", {"zone_code": "z1", "kills": 99})
    p = rules.apply_event(objs, p, "level", {"level": 60})
    assert p == [10, 50, 0] and not rules.complete(objs, p, collected={})
    p = rules.apply_event(
        objs, rules.apply_event(objs, p, "action", {"action": "trade"}), "action", {"action": "trade"}
    )
    assert rules.complete(objs, p, collected={})
    assert rules.level_rarity(CFG, 1) == "bronze" and rules.level_rarity(CFG, 1000) == "relic"
    pr = rules.prestige(CFG, 120, 5 * CFG.prestige.mastery_xp_per_point)
    assert pr["points"] == 125 and pr["rarity"] == "silver" and pr["next"]["rarity"] == "gold"


async def test_quest_graph_validation_rejects_cycles(make_client) -> None:  # type: ignore[no-untyped-def]
    gd = await make_client("game_designer")
    base = {"quest_type": "kill", "objectives": [{"kind": "kill", "count": 1}]}
    assert (await gd.http.post(f"{ADMIN}/quest", json={"code": "cyc_a", "data": base})).status_code == 201
    r = await gd.http.post(f"{ADMIN}/quest", json={"code": "cyc_b", "data": {**base, "prerequisites": ["cyc_a"]}})
    assert r.status_code == 201
    cur = (await gd.http.get(f"{ADMIN}/quest/cyc_a")).json()
    body = {"data": {**base, "prerequisites": ["cyc_b"]}, "expected_version": cur["edit_version"]}
    up = await gd.http.put(f"{ADMIN}/quest/cyc_a", json=body)
    assert up.status_code == 200, up.text
    v = (await gd.http.post(f"{ADMIN}/quest/cyc_a/validate")).json()
    assert not v["ok"] and any(i["code"] == "prerequisite_cycle" for i in v["issues"])
    bad = await gd.http.post(
        f"{ADMIN}/quest", json={"code": "cyc_c", "data": {**base, "objectives": [{"kind": "explore"}]}}
    )
    assert bad.status_code == 422


async def test_tutorial_chain_progresses_from_aggregated_events(make_client, make_character, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from app.services import afk

    clock = Clock()
    monkeypatch.setattr(afk, "now_utc", clock)
    staff = await make_client("admin")
    u, cid = await afk_hero(make_client, make_character)
    log = (await u.http.get(Q(cid))).json()
    assert "first_steps" in {q["code"] for q in log["available"]} and "into_the_meadows" in {
        q["code"] for q in log["locked"]
    }
    assert (await u.http.post(f"{Q(cid)}/into_the_meadows/accept")).json()["error"]["code"] == "quest_locked"
    assert (await u.http.post(f"{Q(cid)}/first_steps/accept")).json()["status"] == "active"
    early = await u.http.post(f"{Q(cid)}/first_steps/claim", headers={"Idempotency-Key": _key()})
    assert early.json()["error"]["code"] == "quest_incomplete"
    sword = await _grant(staff, cid, "worn_training_sword")
    assert (
        await u.http.post(f"/api/v1/characters/{cid}/equipment/equip", json={"instance_id": sword})
    ).status_code == 200
    key = _key()
    c = await u.http.post(f"{Q(cid)}/first_steps/claim", headers={"Idempotency-Key": key})
    assert c.status_code == 200, c.text
    assert c.json()["xp"]["xp_gained"] == 200 and c.json()["gold"] == 20
    assert (await u.http.post(f"{Q(cid)}/first_steps/claim", headers={"Idempotency-Key": key})).json()["replayed"]
    assert (await u.http.post(f"{Q(cid)}/first_steps/claim", headers={"Idempotency-Key": _key()})).json()["error"][
        "code"
    ] == "quest_done"
    assert (await u.http.post(f"{Q(cid)}/into_the_meadows/accept")).status_code == 200
    assert (await _start(u, cid, duration=600)).status_code == 201
    from datetime import timedelta

    clock.now += timedelta(minutes=11)
    assert (
        await u.http.post(f"/api/v1/characters/{cid}/afk/claim", headers={"Idempotency-Key": _key()})
    ).status_code == 200
    active = {q["code"]: q for q in (await u.http.get(Q(cid))).json()["active"]}
    assert active["into_the_meadows"]["status"] == "completed" and active["into_the_meadows"]["progress"] == [1, 1]
    ach = (await u.http.get(f"/api/v1/characters/{cid}/achievements")).json()
    assert ach["counters"]["afk_sessions"] == 1 and ach["counters"]["kills"] >= 0


async def test_collect_and_profession_quests_consume_and_repeat(make_client, make_character) -> None:  # type: ignore[no-untyped-def]
    staff = await make_client("admin")
    u = await make_client()
    cid = await make_character(u.user_id, level=20)
    r = await staff.http.post(
        f"/api/v1/admin/characters/{cid}/professions/herbalism/xp",
        json={"amount": 5000, "reason": "t"},
        headers={"Idempotency-Key": _key()},
    )
    assert r.status_code == 200
    assert (await u.http.post(f"{Q(cid)}/herbal_beginnings/accept")).json()[
        "status"
    ] == "completed"  # seeded from level
    assert (
        await u.http.post(f"{Q(cid)}/herbal_beginnings/claim", headers={"Idempotency-Key": _key()})
    ).status_code == 200
    await u.http.post(f"{Q(cid)}/silverleaf_supply/accept")
    assert (await u.http.post(f"{Q(cid)}/silverleaf_supply/claim", headers={"Idempotency-Key": _key()})).json()[
        "error"
    ]["code"] == "quest_incomplete"
    await _grant(staff, cid, "silverleaf", 12)
    assert (
        await u.http.post(f"{Q(cid)}/silverleaf_supply/claim", headers={"Idempotency-Key": _key()})
    ).status_code == 200
    from app.services import crafting

    async with get_sessionmaker()() as db:
        assert await crafting.count_in_bag(db, cid, "silverleaf") == 2
    assert (await u.http.post(f"{Q(cid)}/silverleaf_supply/accept")).json()["status"] == "active"  # repeatable


async def test_achievements_titles_and_selection(make_client, make_character) -> None:  # type: ignore[no-untyped-def]
    u = await make_client()
    cid = await make_character(u.user_id, level=250)
    async with get_sessionmaker()() as db:
        ch = await db.get(Character, cid)
        assert ch is not None
        await goals.bump(db, ch, add={"kills": 250_000})
        await db.commit()
    ach = (await u.http.get(f"/api/v1/characters/{cid}/achievements")).json()
    got = {a["code"] for a in ach["achievements"] if a["unlocked_at"]}
    assert {"slayer_1", "slayer_2", "slayer_3"} <= got and ach["points"] >= 60
    t = (await u.http.get(f"/api/v1/characters/{cid}/titles")).json()
    by = {x["ref"]: x for x in t["titles"]}
    assert by["earned:slayer"]["rarity"] == "gold" and by["level:seasoned"]["rarity"] == "silver"
    assert "class" in by and "race" in by and t["selected"] == "level:seasoned"
    assert (
        await u.http.post(f"/api/v1/characters/{cid}/titles/select", json={"ref": "earned:slayer"})
    ).status_code == 200
    assert (await u.http.get(f"/api/v1/characters/{cid}/titles")).json()["selected"] == "earned:slayer"
    bad = await u.http.post(f"/api/v1/characters/{cid}/titles/select", json={"ref": "earned:worldbreaker"})
    assert bad.json()["error"]["code"] == "title_unavailable"
    col = (await u.http.get(f"/api/v1/characters/{cid}/collections")).json()
    assert {"total", "owned", "groups"} <= set(col)


async def test_promotion_can_require_quest_by_config(make_client, make_character, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    strict = CFG.model_copy(update={"promotion_quest_required": {"promotion": True, "specialization": False}})

    async def cfg(_db):  # type: ignore[no-untyped-def]
        return strict

    monkeypatch.setattr(goals, "config", cfg)
    u = await make_client()
    cid = await make_character(u.user_id, level=100, base_class_id=await _class_id("warrior"))
    r = await u.http.post(f"/api/v1/characters/{cid}/class/promote", json={"branch_code": "guardian"})
    assert r.json()["error"]["code"] == "promotion_quest_required"
    async with get_sessionmaker()() as db:
        rev = (
            await db.execute(select(goals.Quest.revision_no).where(goals.Quest.code == "trial_of_the_branch"))
        ).scalar_one()
        db.add(
            CharacterQuest(
                character_id=cid,
                quest_code="trial_of_the_branch",
                quest_revision_no=rev,
                status="claimed",
                progress=[100, 100],
                times_completed=1,
            )
        )
        await db.commit()
    ok = await u.http.post(f"/api/v1/characters/{cid}/class/promote", json={"branch_code": "guardian"})
    assert ok.status_code == 200, ok.text
