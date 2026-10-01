"""Phase 25: balance simulator (sandboxed, deterministic, exportable), balance checker and aggregate telemetry."""

from sqlalchemy import func, select

from app.content.loader import load_yaml
from app.game_engine import simulator as sim
from app.game_engine.item_generator import ItemStudioConfig
from app.game_engine.items import ItemRules
from app.models.character import Character
from app.services import telemetry

B = "/api/v1/admin/balance"
CFG = sim.SimulatorConfig.model_validate(load_yaml("balance/simulator.yaml")["data"])


def test_synthetic_gear_scales_with_budget_and_tier() -> None:
    gen = ItemStudioConfig.model_validate(load_yaml("balance/item_studio.yaml")["data"]).generator
    rules = ItemRules.model_validate(load_yaml("balance/item_rules.yaml")["data"])
    full = {e["params"]["stat"]: e["params"]["amount"] for e in sim.synthetic_gear(CFG, gen, rules, "warrior", 3, 100)}
    half = {e["params"]["stat"]: e["params"]["amount"] for e in sim.synthetic_gear(CFG, gen, rules, "warrior", 3, 50)}
    t5 = {e["params"]["stat"]: e["params"]["amount"] for e in sim.synthetic_gear(CFG, gen, rules, "warrior", 5, 100)}
    assert full["attack_power"] > 0 and abs(half["attack_power"] - full["attack_power"] / 2) < 0.1
    assert t5["armor"] > full["armor"] and sim.synthetic_gear(CFG, gen, rules, "warrior", -1, 100) == []
    assert sim.pct_delta(105, 100) == 5.0 and sim.summarize([1, 3])["mean"] == 2


async def test_simulate_is_sandboxed_deterministic_and_exportable(make_client, db) -> None:  # type: ignore[no-untyped-def]
    gd = await make_client("game_designer")
    before = (await db.execute(select(func.count()).select_from(Character))).scalar_one()
    body = {
        "level": 60,
        "base_class": "warrior",
        "iterations": 2,
        "fights": 3,
        "duration_s": 3600,
        "profession_node": "meadow_herbs",
    }
    r1 = await gd.http.post(f"{B}/simulate", json=body)
    assert r1.status_code == 200, r1.text
    out = r1.json()
    assert set(out["metrics"]) == {
        "kills_per_hour",
        "xp_per_hour",
        "gold_per_hour",
        "loot_value_per_hour",
        "potions_per_hour",
        "death_probability",
    }
    assert {"dps", "hps", "effective_damage_taken_per_s", "support_contribution_per_s", "win_rate"} <= set(
        out["combat"]
    )
    assert (
        len(out["per_iteration"]) == 2
        and out["profession"]["profession"] == "herbalism"
        and out["zone"] == "mistfen_marsh"
    )
    assert (await gd.http.post(f"{B}/simulate", json=body)).json()["per_iteration"] == out["per_iteration"]
    csv = await gd.http.post(f"{B}/simulate", params={"format": "csv"}, json=body)
    assert csv.headers["content-type"].startswith("text/csv") and "kills_per_hour" in csv.text.splitlines()[0]
    after = (await db.execute(select(func.count()).select_from(Character))).scalar_one()
    assert after == before  # sandbox rolled back
    bad = await gd.http.post(f"{B}/simulate", json={**body, "duration_s": 4 * 3600})
    assert bad.status_code == 422
    player = await make_client()
    assert (await player.http.post(f"{B}/simulate", json=body)).status_code == 403


async def test_balance_checker_reports_without_changing_anything(make_client) -> None:  # type: ignore[no-untyped-def]
    gd = await make_client("game_designer")
    r = await gd.http.post(f"{B}/check", json={"level": 50, "sections": ["support", "items"], "fights": 2})
    assert r.status_code == 200, r.text
    rep = r.json()
    rows = rep["sections"]["support"]
    assert len(rows) == 10 and all("vs_dps_pct" in x for x in rows)
    assert {"checked", "outliers", "impossible_requirements"} <= set(rep["sections"]["items"])
    assert all({"section", "subject", "message"} <= set(w) for w in rep["warnings"])


async def test_telemetry_is_aggregate_and_suppresses_small_buckets(make_client) -> None:  # type: ignore[no-untyped-def]
    assert telemetry._suppress({"a": 10, "b": 1, "c": 2}) == {"a": 10, "other": 3}
    gd = await make_client("game_designer")
    t = (await gd.http.get("/api/v1/admin/telemetry", params={"days": 30})).json()
    assert {"sessions", "zones", "profession_usage", "funnel"} <= set(t)
    assert [s["step"] for s in t["funnel"]] == [
        "registered",
        "created_character",
        "started_afk",
        "claimed_afk",
        "reached_level_10",
        "reached_level_100",
    ]
    assert all(v >= telemetry.MIN_BUCKET for k, v in t["zones"].items() if k != "other")
    text = str(t)
    assert "@" not in text and "email" not in text  # no personal data in the payload
    player = await make_client()
    assert (await player.http.get("/api/v1/admin/telemetry")).status_code == 403
