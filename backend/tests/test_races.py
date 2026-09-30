import uuid

from sqlalchemy import select

from app.db.session import get_sessionmaker
from app.models.race import Race

CANON = {
    "human": ("Adaptable", "Diplomat"),
    "high_elf": ("Arcane Blood", "Starborn"),
    "dark_elf": ("Night Instinct", "Umbral"),
    "dwarf": ("Stoneborn", "Deepforged"),
    "orc": ("Blood Fury", "Warborn"),
    "sylvan": ("Nature Bond", "Greenwarden"),
    "beastkin": ("Predator Sense", "Wildblood"),
    "revenant": ("Undying Will", "Deathless"),
}


async def _race_id(code: str) -> int:
    async with get_sessionmaker()() as s:
        return (await s.execute(select(Race.id).where(Race.code == code))).scalar_one()


async def test_exactly_eight_canonical_races(client) -> None:  # type: ignore[no-untyped-def]
    r = await client.get("/api/v1/content/races", params={"locale": "en"})
    races = {x["code"]: x for x in r.json()}
    assert set(races) == set(CANON)
    for code, (trait, title) in CANON.items():
        assert races[code]["trait_name"] == trait and races[code]["title"] == title


async def test_races_localized_in_all_locales(client) -> None:  # type: ignore[no-untyped-def]
    expected = {"tr": "Cüce", "zh-CN": "矮人", "es": "Enano"}
    for loc, name in expected.items():
        races = {x["code"]: x for x in (await client.get("/api/v1/content/races", params={"locale": loc})).json()}
        assert races["dwarf"]["name"] == name
        assert races["dwarf"]["labels"]["stat.vit.name"] != "Vit"


async def test_character_options_include_races_without_class_locks(client) -> None:  # type: ignore[no-untyped-def]
    opts = (await client.get("/api/v1/content/character-options")).json()
    assert len(opts["races"]) == 8
    assert all("affinity" in r for r in opts["races"])  # informational only; no allowed_classes field
    assert all("allowed_classes" not in r for r in opts["races"])


async def test_racial_effects_in_stat_breakdown(make_client, make_character) -> None:  # type: ignore[no-untyped-def]
    u = await make_client()
    cid = await make_character(u.user_id, race_id=await _race_id("dwarf"))
    v = (await u.http.get(f"/api/v1/characters/{cid}/progression")).json()
    vit = v["stats"]["primary"]["VIT"]
    assert {"source": "race", "ref": "dwarf", "flat": 0.0, "percent": 5.0} in vit["breakdown"]
    assert vit["final"] == (5 + 3) * 1.05  # (base + warrior VIT) × dwarf 5%
    be = v["stats"]["derived"]["block_efficiency"]
    assert any(b["source"] == "race" and b["flat"] == 5 for b in be["breakdown"])


async def test_human_respec_discount(make_client, make_character) -> None:  # type: ignore[no-untyped-def]
    u = await make_client()
    human = await make_character(u.user_id, level=700, unspent=10, race_id=await _race_id("human"))
    orc = await make_character(u.user_id, level=700, unspent=10, race_id=await _race_id("orc"))
    for cid in (human, orc):
        ver = (await u.http.get(f"/api/v1/characters/{cid}/progression")).json()["version"]
        await u.http.post(
            f"/api/v1/characters/{cid}/stats/allocate",
            json={"points": {"STR": 10}, "expected_version": ver},
            headers={"Idempotency-Key": uuid.uuid4().hex},
        )
    qh = (await u.http.get(f"/api/v1/characters/{human}/stats/respec-quote")).json()
    qo = (await u.http.get(f"/api/v1/characters/{orc}/stats/respec-quote")).json()
    assert qo["gold_cost"] == 1200 and qh["gold_cost"] == 600 and qh["discount_limit_points"] == 300


async def test_balance_validator_blocks_overpowered_race(make_client) -> None:  # type: ignore[no-untyped-def]
    gd = await make_client("game_designer")
    base = {
        "sort_order": 99,
        "identity": "test",
        "trait_name_key": "race.x.trait_name",
        "trait_description_key": "race.x.trait_description",
        "title_key": "race.x.title",
        "affinity": [],
    }
    strong = f"test_race_{uuid.uuid4().hex[:6]}"
    op = f"test_race_{uuid.uuid4().hex[:6]}"
    await gd.http.post(
        "/api/v1/admin/content/race",
        json={
            "code": strong,
            "data": {**base, "effects": [{"effect_type": "STAT_PERCENT", "params": {"stat": "STR", "percent": 12}}]},
        },
    )
    await gd.http.post(
        "/api/v1/admin/content/race",
        json={
            "code": op,
            "data": {**base, "effects": [{"effect_type": "DAMAGE_MULTIPLIER", "params": {"percent": 15}}]},
        },
    )
    v1 = (await gd.http.post(f"/api/v1/admin/content/race/{strong}/validate")).json()
    assert v1["ok"] is True and v1["issues"][0]["code"] == "race_strong"
    blocked = await gd.http.post(
        "/api/v1/admin/content/releases", json={"items": [{"entity_type": "race", "code": strong}]}
    )
    assert blocked.status_code == 422  # warning requires acknowledgement
    ok = await gd.http.post(
        "/api/v1/admin/content/releases",
        json={"items": [{"entity_type": "race", "code": strong}], "acknowledge_warnings": True},
    )
    assert ok.status_code == 200
    v2 = (await gd.http.post(f"/api/v1/admin/content/race/{op}/validate")).json()
    assert v2["ok"] is False and v2["issues"][0]["code"] == "race_overpowered"
    bad_effect = f"test_race_{uuid.uuid4().hex[:6]}"
    await gd.http.post(
        "/api/v1/admin/content/race",
        json={"code": bad_effect, "data": {**base, "effects": [{"effect_type": "RUN_SCRIPT", "params": {}}]}},
    )
    v3 = (await gd.http.post(f"/api/v1/admin/content/race/{bad_effect}/validate")).json()
    assert v3["issues"][0]["code"] == "invalid_effect"
    # archive the test race so it does not leak into player-facing race lists
    await gd.http.post(f"/api/v1/admin/content/race/{strong}/status", json={"status": "archived"})


async def test_canonical_races_pass_balance_validator(make_client) -> None:  # type: ignore[no-untyped-def]
    gd = await make_client("game_designer")
    for code in CANON:
        v = (await gd.http.post(f"/api/v1/admin/content/race/{code}/validate")).json()
        assert v == {"ok": True, "issues": []}, code
