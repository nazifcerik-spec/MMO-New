import uuid

from sqlalchemy import select

from app.db.session import get_sessionmaker
from app.models.classes import BaseClass

GRAPH = {
    "warrior": {"guardian": ["iron_bastion", "warlord"], "reaver": ["berserker", "weapon_master"]},
    "rogue": {"assassin": ["nightblade", "venomancer"], "duelist": ["blade_dancer", "trickster"]},
    "ranger": {"marksman": ["sharpshooter", "arbalist"], "scout": ["beastmaster", "trapper"]},
    "mage": {"arcanist": ["runemaster", "chronomancer"], "elementalist": ["pyromancer", "cryomancer"]},
    "monk": {"disciple": ["iron_body", "spirit_walker"], "striker": ["combo_master", "storm_fist"]},
    "cleric": {"saint": ["high_priest", "aegis_priest"], "oracle": ["prophet", "exorcist"]},
    "paladin": {"warden": ["aegis_knight", "lightwarden"], "crusader": ["templar", "justicar"]},
    "druid": {"grovekeeper": ["lifebinder", "thorn_sage"], "shapeshifter": ["bearwarden", "mooncaller"]},
    "bard": {"minstrel": ["virtuoso", "harmonist"], "skald": ["war_chanter", "dirge_singer"]},
    "shaman": {"totemist": ["earthwarden", "storm_totemist"], "spiritcaller": ["ancestor_sage", "hexer"]},
}
SUPPORT = {"cleric", "paladin", "druid", "bard", "shaman"}


async def _class_id(code: str) -> int:
    async with get_sessionmaker()() as s:
        return (await s.execute(select(BaseClass.id).where(BaseClass.code == code))).scalar_one()


def _key() -> str:
    return uuid.uuid4().hex


async def test_class_graph_is_canonical_with_exactly_40_specializations(client) -> None:  # type: ignore[no-untyped-def]
    cards = (await client.get("/api/v1/content/classes")).json()
    graph = {c["code"]: {b["code"]: [s["code"] for s in b["specializations"]] for b in c["branches"]} for c in cards}
    assert graph == GRAPH
    assert sum(len(specs) for c in graph.values() for specs in c.values()) == 40
    assert sum(len(c) for c in graph.values()) == 20
    cats = {c["code"]: c["category"] for c in cards}
    assert {k for k, v in cats.items() if v == "support"} == SUPPORT and len(cats) == 10


async def test_supports_have_canonical_solo_accord(client) -> None:  # type: ignore[no-untyped-def]
    cards = (await client.get("/api/v1/content/classes")).json()
    for c in cards:
        if c["category"] == "support":
            assert c["solo_accord"]["conversion_percent"] == 35
        else:
            assert c["solo_accord"] is None


async def test_classes_localized(client) -> None:  # type: ignore[no-untyped-def]
    zh = {c["code"]: c for c in (await client.get("/api/v1/content/classes", params={"locale": "zh-CN"})).json()}
    assert zh["warrior"]["name"] == "战士" and zh["warrior"]["branches"][0]["name"] == "守护者"
    tr = {c["code"]: c for c in (await client.get("/api/v1/content/classes", params={"locale": "tr"})).json()}
    assert tr["bard"]["resources"] == ["Ritim"]


async def test_create_character_via_api_with_race_and_class(make_client) -> None:  # type: ignore[no-untyped-def]
    u = await make_client()
    opts = (await u.http.get("/api/v1/content/character-options")).json()
    race = next(r for r in opts["races"] if r["code"] == "orc")
    cls = next(c for c in opts["base_classes"] if c["code"] == "shaman")
    name = "Zug" + "".join(chr(97 + b % 26) for b in uuid.uuid4().bytes[:6])
    r = await u.http.post("/api/v1/characters", json={"name": name, "race_id": race["id"], "base_class_id": cls["id"]})
    assert r.status_code == 201, r.text
    dup = await u.http.post(
        "/api/v1/characters", json={"name": name.upper(), "race_id": race["id"], "base_class_id": cls["id"]}
    )
    assert dup.status_code == 409 and dup.json()["error"]["code"] == "name_taken"
    bad = await u.http.post(
        "/api/v1/characters", json={"name": "Validname", "race_id": race["id"], "base_class_id": 999999}
    )
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "invalid_class"
    view = (await u.http.get(f"/api/v1/characters/{r.json()['id']}/class")).json()
    assert view["class_title"] == "Shaman" and view["can_promote"] is False


async def test_promotion_and_specialization_rules(make_client, make_character) -> None:  # type: ignore[no-untyped-def]
    u = await make_client()
    low = await make_character(u.user_id, level=99, base_class_id=await _class_id("warrior"))
    r = await u.http.post(f"/api/v1/characters/{low}/class/promote", json={"branch_code": "guardian"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "level_too_low"

    cid = await make_character(u.user_id, level=300, base_class_id=await _class_id("warrior"))
    spec_first = await u.http.post(
        f"/api/v1/characters/{cid}/class/specialize", json={"specialization_code": "iron_bastion"}
    )
    assert spec_first.json()["error"]["code"] == "promotion_required"
    wrong = await u.http.post(f"/api/v1/characters/{cid}/class/promote", json={"branch_code": "assassin"})
    assert wrong.status_code == 422 and wrong.json()["error"]["code"] == "invalid_branch"
    ok = await u.http.post(f"/api/v1/characters/{cid}/class/promote", json={"branch_code": "guardian"})
    assert ok.status_code == 200 and ok.json()["class_title"] == "Guardian"
    dup = await u.http.post(f"/api/v1/characters/{cid}/class/promote", json={"branch_code": "reaver"})
    assert dup.status_code == 409 and dup.json()["error"]["code"] == "already_promoted"
    other_branch = await u.http.post(
        f"/api/v1/characters/{cid}/class/specialize", json={"specialization_code": "berserker"}
    )
    assert other_branch.json()["error"]["code"] == "invalid_specialization"
    sp = await u.http.post(f"/api/v1/characters/{cid}/class/specialize", json={"specialization_code": "iron_bastion"})
    assert sp.status_code == 200 and sp.json()["class_title"] == "Iron Bastion"
    again = await u.http.post(f"/api/v1/characters/{cid}/class/specialize", json={"specialization_code": "warlord"})
    assert again.status_code == 409


async def test_generic_class_title_transformations(make_client, make_character) -> None:  # type: ignore[no-untyped-def]
    admin = await make_client("admin")
    u = await make_client()
    cid = await make_character(u.user_id, level=300, base_class_id=await _class_id("warrior"))
    await u.http.post(f"/api/v1/characters/{cid}/class/promote", json={"branch_code": "guardian"})
    await u.http.post(f"/api/v1/characters/{cid}/class/specialize", json={"specialization_code": "iron_bastion"})
    from app.services import progression

    async with get_sessionmaker()() as s:
        cfg = await progression.load_config(s)

    async def level_to(target: int) -> dict:
        cur = (await u.http.get(f"/api/v1/characters/{cid}/progression")).json()
        need = sum(cfg.xp_table[cur["level"] : target]) - cur["xp"]
        await admin.http.post(
            f"/api/v1/admin/characters/{cid}/xp",
            json={"amount": need, "reason": "test"},
            headers={"Idempotency-Key": _key()},
        )
        return (await u.http.get(f"/api/v1/characters/{cid}/class", params={"locale": "en"})).json()

    assert (await level_to(600))["class_title"] == "Awakened Iron Bastion"
    assert (await level_to(850))["class_title"] == "Ascendant Iron Bastion"
    final = await level_to(1000)
    assert final["class_title"] == "Eternal Bastion"
    assert all(s["completed_at"] for s in final["stages"])
    tr = (await u.http.get(f"/api/v1/characters/{cid}/class", params={"locale": "tr"})).json()
    assert tr["class_title"] == "Ebedi Kale"


async def test_class_stats_flow_into_sheet(make_client, make_character) -> None:  # type: ignore[no-untyped-def]
    u = await make_client()
    cid = await make_character(u.user_id, level=100, base_class_id=await _class_id("warrior"))
    await u.http.post(f"/api/v1/characters/{cid}/class/promote", json={"branch_code": "guardian"})
    v = (await u.http.get(f"/api/v1/characters/{cid}/progression")).json()
    armor = v["stats"]["derived"]["armor"]
    assert any(b["source"] == "class" and b["ref"] == "guardian" and b["percent"] == 12 for b in armor["breakdown"])


async def test_path_change_first_free_then_paid_with_cooldown(make_client, make_character) -> None:  # type: ignore[no-untyped-def]
    u = await make_client()
    cid = await make_character(u.user_id, level=150, base_class_id=await _class_id("mage"))
    await u.http.post(f"/api/v1/characters/{cid}/class/promote", json={"branch_code": "arcanist"})
    q = (await u.http.get(f"/api/v1/characters/{cid}/class")).json()["path_change"]
    assert q["free"] is True
    r = await u.http.post(
        f"/api/v1/characters/{cid}/class/change-path",
        json={"branch_code": "elementalist"},
        headers={"Idempotency-Key": _key()},
    )
    assert r.status_code == 200 and r.json()["branch_code"] == "elementalist"
    cd = await u.http.post(
        f"/api/v1/characters/{cid}/class/change-path",
        json={"branch_code": "arcanist"},
        headers={"Idempotency-Key": _key()},
    )
    assert cd.status_code == 409 and cd.json()["error"]["code"] == "path_change_cooldown"
    other = await u.http.post(
        f"/api/v1/characters/{cid}/class/change-path",
        json={"branch_code": "guardian"},
        headers={"Idempotency-Key": _key()},
    )
    assert other.status_code in (409, 422)


async def test_validator_rejects_third_branch(make_client) -> None:  # type: ignore[no-untyped-def]
    gd = await make_client("game_designer")
    code = f"extra_branch_{uuid.uuid4().hex[:6]}"
    r = await gd.http.post(
        "/api/v1/admin/content/class_branch",
        json={
            "code": code,
            "data": {
                "base_class_code": "warrior",
                "sort_order": 3,
                "role_key": "branch.x.role",
                "passive_code": "x",
                "effects": [],
            },
        },
    )
    assert r.status_code == 201
    v = (await gd.http.post(f"/api/v1/admin/content/class_branch/{code}/validate")).json()
    assert v["ok"] is False and v["issues"][0]["code"] == "too_many_branches"
    spec = f"extra_spec_{uuid.uuid4().hex[:6]}"
    await gd.http.post(
        "/api/v1/admin/content/specialization",
        json={
            "code": spec,
            "data": {
                "branch_code": "guardian",
                "sort_order": 3,
                "role_key": "x",
                "mastery_noun_key": "x",
                "passive_code": "x",
                "effects": [],
            },
        },
    )
    v2 = (await gd.http.post(f"/api/v1/admin/content/specialization/{spec}/validate")).json()
    assert v2["issues"][0]["code"] == "too_many_specializations"
    await gd.http.delete(f"/api/v1/admin/content/class_branch/{code}")
    await gd.http.delete(f"/api/v1/admin/content/specialization/{spec}")
