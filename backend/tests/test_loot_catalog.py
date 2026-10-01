"""Phase 19: loot rules (LUK diminishing returns, conditions, pity, rarity rolls, ownership limits) and the
deterministic 1,520-template launch catalog (generation, validation, idempotent commit, RBAC)."""

from collections import Counter

from sqlalchemy import select

from app.content.loader import load_yaml
from app.db.session import get_sessionmaker
from app.game_engine import catalog as cat_engine
from app.game_engine import loot
from app.game_engine.item_generator import ItemStudioConfig
from app.game_engine.items import ItemRules
from app.game_engine.rng import Rng
from app.localization import service as l10n
from app.models.character import Character
from app.models.items import ItemTemplate
from app.services import catalog, inventory

LOOT = loot.LootConfig.model_validate(load_yaml("balance/loot.yaml")["data"])
CFG = load_yaml("catalog/launch_catalog.yaml")


def _rows() -> list[dict]:  # type: ignore[type-arg]
    rules = ItemRules.model_validate(load_yaml("balance/item_rules.yaml")["data"])
    gen = ItemStudioConfig.model_validate(load_yaml("balance/item_studio.yaml")["data"]).generator
    ref = load_yaml("classes/reference.yaml")
    return cat_engine.generate(
        CFG, rules, gen, weapon_families=ref["weapon_families"], armor_families=ref["armor_families"],
        professions=load_yaml("professions/professions.yaml")["professions"],
    )  # fmt: skip


def test_luck_has_small_diminishing_returns() -> None:
    vals = [loot.luck_bonus(LOOT, x) for x in (0, 300, 600, 1200, 5000, 10**6)]
    assert vals[0] == 0 and vals == sorted(vals) and vals[-1] < LOOT.luck.max_rare_bonus_pct
    assert vals[2] - vals[1] < vals[1] - vals[0]  # diminishing
    assert loot.luck_bonus(LOOT, 600) == LOOT.luck.max_rare_bonus_pct / 2


def test_rarity_roll_is_deterministic_and_luck_shift_is_modest() -> None:
    base = [loot.roll_rarity(LOOT, Rng(s), 0) for s in range(4000)]
    assert base == [loot.roll_rarity(LOOT, Rng(s), 0) for s in range(4000)]
    lucky = [loot.roll_rarity(LOOT, Rng(s), loot.luck_bonus(LOOT, 5000)) for s in range(4000)]
    share = lambda xs: sum(loot.is_rare(LOOT, r) for r in xs) / len(xs)  # noqa: E731
    assert share(base) < share(lucky) < share(base) * 1.2
    assert all(loot.is_rare(LOOT, loot.roll_rarity(LOOT, Rng(s), 0, force_rare=True)) for s in range(200))


def test_drop_conditions_and_pity() -> None:
    entries = [
        {"kind": "material", "ref": "ore", "weight": 50},
        {"kind": "material", "ref": "frost", "weight": 50, "conditions": {"zone_tags": ["cold"]}},
        {"kind": "item", "ref": "crown", "weight": 50, "boss_only": True, "rare": True, "chance_pct": 1},
        {"kind": "item_pool", "tier": 3, "weight": 1, "chance_pct": 1},
        {"kind": "item", "ref": "late", "weight": 50, "conditions": {"min_level": 500}},
    ]
    ctx = {"boss": False, "zone_tags": ["forest"], "level": 100}
    rolled = [loot.roll_table(LOOT, Rng(s), 1, entries, ctx, rare_bonus_pct=0, force_rare=False) for s in range(500)]
    refs = Counter(d.get("ref") for r in rolled for d in r)
    assert set(refs) <= {"ore", None} and refs["ore"] > 0
    forced = [loot.roll_table(LOOT, Rng(s), 1, entries, ctx, rare_bonus_pct=0, force_rare=True) for s in range(100)]
    assert all(len(f) == 1 and f[0]["rare"] and f[0]["kind"] == "item_pool" for f in forced)
    boss = loot.roll_table(LOOT, Rng(1), 1, entries, {**ctx, "boss": True}, rare_bonus_pct=0, force_rare=True)
    assert boss[0]["rare"]


def test_catalog_hits_exact_targets_deterministically() -> None:
    rows = _rows()
    assert rows == _rows()
    d = cat_engine.distribution(rows)
    assert d["total"] == 1520 and d["by_category"] == CFG["targets"]
    assert d["duplicate_codes"] == 0 and d["duplicate_names"] == {"en": 0, "tr": 0, "zh-CN": 0, "es": 0}
    for c in ("weapon", "armor", "accessory", "profession_tool", "material"):
        assert set(d["tier_by_category"][c]) == set(range(11))
    relics = [r for r in rows if r["data"]["rarity"] == "relic"]
    assert relics and all(r["data"]["tier"] == 10 and r["data"]["affix_rules"]["fixed"] for r in relics)
    assert all(
        r["data"]["rarity"] != "relic"
        for r in rows
        if r["kind"] not in ("weapon", "armor", "accessory", "profession_tool")
    )
    assert all(set(r["l10n"]["name"]) == {"en", "tr", "zh-CN", "es"} for r in rows)
    epithets = Counter(r["code"].rsplit("_", 1)[-1] for r in rows)
    assert max(epithets.values()) < 0.06 * len(rows)  # naming tokens spread, no single dominant pattern


async def test_catalog_dry_run_passes_real_validators(db) -> None:  # type: ignore[no-untyped-def]
    s = await catalog.dry_run(db)
    assert s["matches_targets"] and s["errors"] == 0, s["issue_codes"]
    md = catalog.report_markdown(s)
    assert "| weapon | 280 | 280 |" in md and "Stat budget outliers" in md


async def test_catalog_commit_is_idempotent_and_owned_limits_apply(db, make_client, make_character) -> None:  # type: ignore[no-untyped-def]
    rows = {r["code"]: r for r in _rows()}
    relic = next(c for c, r in rows.items() if r["data"]["rarity"] == "relic" and r["kind"] == "weapon")
    salvage = rows[relic]["data"]["salvage"][0]["template_code"]
    only = {relic, salvage, "ore_t0_dawn"}
    first = await catalog.commit(db, publish=True, actor_id=None, only=only)
    await db.commit()
    assert first["created"] == 3 and first["published"] == 3
    again = await catalog.commit(db, publish=True, actor_id=None, only=only)
    assert again["created"] == 0
    tpl = (await db.execute(select(ItemTemplate).where(ItemTemplate.code == relic))).scalar_one()
    assert tpl.status == "published" and tpl.tier == 10
    texts = (await l10n.get_all_locales(db, [f"item.{relic}.name"]))[f"item.{relic}.name"]
    assert texts["en"]["status"] == "published" and texts["tr"]["status"] == "draft" and texts["zh-CN"]["value"]
    # ownership limit: relic limit 1 -> the second copy is auto-sold, never duplicated
    u = await make_client()
    cid = await make_character(u.user_id, level=950)
    async with get_sessionmaker()() as s2:
        ch = await s2.get(Character, cid)
        out = await inventory.grant_afk_loot(s2, ch, [{"kind": "item", "ref": relic, "qty": 2}], "loot-limit-test")  # type: ignore[arg-type]
        await s2.commit()
    assert [o.get("reason") for o in out if o.get("placed") == "sold"] == ["owned_limit"]
    assert sum(1 for o in out if o.get("placed") in ("inventory", "mailbox")) == 1


async def test_catalog_admin_rbac(make_client) -> None:  # type: ignore[no-untyped-def]
    player = await make_client()
    assert (await player.http.get("/api/v1/admin/items/catalog")).status_code == 403
    editor = await make_client("item_editor")
    r = await editor.http.post("/api/v1/admin/items/catalog", json={"publish": True})
    assert r.status_code == 403
