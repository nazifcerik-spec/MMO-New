"""Phase 21: parties (invites/roles/leader/limits/chat) and group AFK (own snapshots, personal loot, contribution)."""

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.content.loader import load_yaml
from app.db.session import get_sessionmaker
from app.game_engine import party as rules
from app.models.afk import AfkSession
from app.models.character import Character
from app.services import party
from tests.test_afk import _hero
from tests.test_classes import _class_id

CFG = rules.PartyConfig.model_validate(load_yaml("balance/party.yaml")["data"])


def _key() -> str:
    return f"k-{uuid.uuid4().hex}"


def P(cid: int) -> str:
    return f"/api/v1/characters/{cid}/party"


async def _name(cid: int) -> str:
    async with get_sessionmaker()() as db:
        return str((await db.execute(select(Character.name).where(Character.id == cid))).scalar_one())


async def _join(leader, lid, member, mid, role=None):  # type: ignore[no-untyped-def]
    inv = await leader.http.post(f"{P(lid)}/invites", json={"character_name": await _name(mid)})
    assert inv.status_code == 201, inv.text
    r = await member.http.post(f"{P(mid)}/invites/{inv.json()['invite_id']}/accept", json={"role": role})
    assert r.status_code == 200, r.text
    return r


def test_composition_bonuses_are_capped_and_role_based() -> None:
    assert [b.code for b in rules.active_bonuses(CFG, ["tank", "healer", "support", "dps", "dps"])] == [
        "frontline_and_mender", "battle_rhythm",
    ]  # fmt: skip
    assert rules.active_bonuses(CFG, ["dps"] * 5) == []
    assert len(rules.active_bonuses(CFG, ["tank", "healer", "support", "dps", "dps"])) <= CFG.max_composition_bonuses


async def test_party_lifecycle_roles_limits_and_leadership(make_client, make_character) -> None:  # type: ignore[no-untyped-def]
    users = [await make_client() for _ in range(CFG.max_size + 1)]
    cls = ["warrior", "cleric", "rogue", "bard", "mage", "ranger"]
    cids = [
        await make_character(u.user_id, level=20, base_class_id=await _class_id(c))
        for u, c in zip(users, cls, strict=True)
    ]
    lead, lid = users[0], cids[0]
    assert (await lead.http.post(P(lid), json={"role": "healer"})).json()["error"]["code"] == "invalid_party_role"
    assert (await lead.http.post(P(lid), json={"role": "tank"})).status_code == 201
    assert (await lead.http.post(P(lid), json={})).json()["error"]["code"] == "already_in_party"
    inv = await lead.http.post(f"{P(lid)}/invites", json={"character_name": await _name(cids[2])})
    bad_role = await users[2].http.post(
        f"{P(cids[2])}/invites/{inv.json()['invite_id']}/accept", json={"role": "healer"}
    )
    assert bad_role.json()["error"]["code"] == "invalid_party_role"
    for i in range(1, CFG.max_size):
        await _join(lead, lid, users[i], cids[i])
    full = await lead.http.post(f"{P(lid)}/invites", json={"character_name": await _name(cids[-1])})
    assert full.json()["error"]["code"] == "party_full"
    alt = await make_character(users[1].user_id, level=20, base_class_id=await _class_id("mage"))
    v = (await lead.http.get(P(lid))).json()["party"]
    assert (
        len(v["members"]) == CFG.max_size
        and v["members"][0]["leader"]
        and "frontline_and_mender" in v["composition_bonuses"]
    )
    assert all({"online", "afk", "role", "class_code"} <= set(m) for m in v["members"])
    # non-leader cannot kick; leader can; leader leaving hands over leadership
    assert (await users[1].http.post(f"{P(cids[1])}/kick", json={"character_id": cids[2]})).status_code == 403
    assert (await lead.http.post(f"{P(lid)}/kick", json={"character_id": cids[2]})).status_code == 204
    same = await lead.http.post(f"{P(lid)}/invites", json={"character_name": await _name(alt)})
    assert same.json()["error"]["code"] == "same_account"
    assert (await lead.http.post(f"{P(lid)}/leave")).status_code == 204
    v2 = (await users[1].http.get(P(cids[1]))).json()["party"]
    assert v2["leader_character_id"] == cids[1] and len(v2["members"]) == CFG.max_size - 2
    for i in range(1, CFG.max_size):
        if i != 2:
            assert (await users[i].http.post(f"{P(cids[i])}/leave")).status_code == 204
    assert (await users[1].http.get(P(cids[1]))).json()["party"] is None


async def test_invite_expiry_and_decline(make_client, make_character, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    a, b = await make_client(), await make_client()
    aid = await make_character(a.user_id, level=10)
    bid = await make_character(b.user_id, level=10)
    await a.http.post(P(aid), json={})
    inv = (await a.http.post(f"{P(aid)}/invites", json={"character_name": await _name(bid)})).json()["invite_id"]
    assert (await b.http.get(P(bid))).json()["invites"][0]["id"] == inv
    real = party.now_utc
    monkeypatch.setattr(party, "now_utc", lambda: real() + timedelta(minutes=CFG.invite_ttl_minutes + 1))
    assert (await b.http.post(f"{P(bid)}/invites/{inv}/accept", json={})).json()["error"]["code"] == "invite_expired"
    monkeypatch.setattr(party, "now_utc", real)
    inv2 = (await a.http.post(f"{P(aid)}/invites", json={"character_name": await _name(bid)})).json()["invite_id"]
    assert (await b.http.post(f"{P(bid)}/invites/{inv2}/decline")).status_code == 204
    assert (await b.http.post(f"{P(bid)}/invites/{inv2}/accept", json={})).json()["error"]["code"] == "invite_closed"


async def test_party_chat_minimal_contract(make_client, make_character) -> None:  # type: ignore[no-untyped-def]
    a, b, c = await make_client(), await make_client(), await make_client()
    aid, bid, cid = [await make_character(u.user_id, level=10) for u in (a, b, c)]
    await a.http.post(P(aid), json={})
    await _join(a, aid, b, bid)
    key = _key()
    r = await a.http.post(f"{P(aid)}/chat", json={"body": "  hello\u0007 team 你好 "}, headers={"Idempotency-Key": key})
    assert r.status_code == 201
    assert (await a.http.post(f"{P(aid)}/chat", json={"body": "dup"}, headers={"Idempotency-Key": key})).json()[
        "replayed"
    ]
    long = await a.http.post(
        f"{P(aid)}/chat", json={"body": "x" * (CFG.chat.max_length + 1)}, headers={"Idempotency-Key": _key()}
    )
    assert long.json()["error"]["code"] == "invalid_message"
    msgs = (await b.http.get(f"{P(bid)}/chat")).json()
    assert [m["body"] for m in msgs] == ["hello team 你好"]
    assert (await b.http.get(f"{P(bid)}/chat", params={"after_id": msgs[-1]["id"]})).json() == []
    assert (await c.http.get(f"{P(cid)}/chat")).json()["error"]["code"] == "not_in_party"


@pytest.fixture
def gclock(monkeypatch):  # type: ignore[no-untyped-def]
    from app.services import afk
    from tests.test_afk import Clock

    c = Clock()
    monkeypatch.setattr(afk, "now_utc", c)
    return c


async def test_group_afk_own_snapshots_personal_loot_and_contribution(make_client, make_character, gclock) -> None:  # type: ignore[no-untyped-def]
    lead, lid = await _hero(make_client, make_character, cls="paladin")
    mate, mid = await _hero(make_client, make_character, cls="warrior")
    await lead.http.post(P(lid), json={"role": "healer"})
    await _join(lead, lid, mate, mid, role="tank")
    assert (
        await mate.http.post(
            f"{P(mid)}/afk",
            json={"zone_code": "whispering_meadows", "duration_s": 3600},
            headers={"Idempotency-Key": _key()},
        )
    ).status_code == 403
    key = _key()
    r = await lead.http.post(
        f"{P(lid)}/afk", json={"zone_code": "whispering_meadows", "duration_s": 3600}, headers={"Idempotency-Key": key}
    )
    assert r.status_code == 201, r.text
    out = r.json()
    assert set(map(int, out["sessions"])) == {lid, mid}
    again = await lead.http.post(
        f"{P(lid)}/afk", json={"zone_code": "whispering_meadows", "duration_s": 3600}, headers={"Idempotency-Key": key}
    )
    assert again.json()["replayed"] and again.json()["group_id"] == out["group_id"]
    async with get_sessionmaker()() as db:
        rows = list((await db.execute(select(AfkSession).where(AfkSession.group_id == out["group_id"]))).scalars())
    assert len(rows) == 2 and len({s.seed for s in rows}) == 1
    by = {s.character_id: s for s in rows}
    assert [p["id"] for p in by[lid].snapshot["party"]] == [f"c{mid}"] and by[lid].snapshot["player"][
        "role"
    ] == "healer"
    assert by[lid].snapshot["loot_salt"] != by[mid].snapshot["loot_salt"]
    hash_before = by[mid].snapshot_hash
    assert (await mate.http.post(f"{P(mid)}/leave")).status_code == 204  # leaving never alters running sessions
    gclock.now += timedelta(hours=1, seconds=5)
    claims = {}
    for u, c in ((lead, lid), (mate, mid)):
        cl = await u.http.post(f"/api/v1/characters/{c}/afk/claim", headers={"Idempotency-Key": _key()})
        assert cl.status_code == 200, cl.text
        claims[c] = cl.json()
    async with get_sessionmaker()() as db:
        assert (await db.get(AfkSession, by[mid].id)).snapshot_hash == hash_before  # type: ignore[union-attr]
    contrib = claims[lid]["result"]["contribution"]
    assert contrib["party_size"] == 2 and contrib["role"] == "healer"
    assert set(contrib["per_fight"]) >= {
        "healing",
        "shield_granted",
        "damage_prevented",
        "ally_buff_uptime_s",
        "debuffs_applied",
        "party_dps_gained",
    }
    assert claims[mid]["result"]["contribution"]["role"] == "tank"
    assert claims[lid]["result"]["fights"] > 0 and claims[mid]["result"]["fights"] > 0
