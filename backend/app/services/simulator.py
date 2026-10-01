"""Balance simulator + class/race balance checker (Phase 25). Decision support only — never changes balance.

Every run builds throwaway characters inside a SAVEPOINT that is always rolled back, then reuses the real
snapshot builder (`afk.build_snapshot`), AFK engine and combat core, so results match live behaviour."""

import csv
import io
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.content.names import name_key
from app.core.errors import NotFoundError, ValidationFailedError
from app.game_engine import afk as afk_engine
from app.game_engine import catalog as catalog_engine
from app.game_engine import simulator as sim
from app.game_engine.combat.engine import simulate
from app.game_engine.combat.models import CombatInput
from app.game_engine.combat.rules import rule_selector, validate_rules
from app.game_engine.crafting import CraftingConfig, resolve_gathering
from app.game_engine.item_generator import ItemStudioConfig
from app.game_engine.items import ItemRules, requirement_problems
from app.game_engine.rng import Rng, derive_seed
from app.game_engine.talents import TalentConfig
from app.game_engine.world import enemy_rules, generate_encounter, rules_by_code_selector
from app.models.abilities import CharacterTalentAllocation
from app.models.auth import User
from app.models.character import Character
from app.models.classes import BaseClass, ClassBranch, Specialization
from app.models.crafting import GatheringNode
from app.models.items import ItemTemplate
from app.models.race import Race
from app.models.world import Zone
from app.services import afk, classes, progression, talents
from app.services.content.types.balance import get_published_balance


class SimParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    level: int = Field(ge=1, le=1000)
    race: str = Field(default="human", max_length=48)
    base_class: str = Field(max_length=48)
    specialization: str | None = Field(default=None, max_length=96)
    talent_build: str = Field(default="auto", max_length=96)  # none | auto | <tree code>
    gear_tier: int | None = Field(default=None, ge=-1, le=10)  # None = tier of the level; -1 = naked
    gear_budget_pct: float = Field(default=100, ge=0, le=300)
    zone: str | None = Field(default=None, max_length=96)
    risk: Literal["safe", "balanced", "elite_hunt", "boss_rush"] = "balanced"
    duration_s: int = Field(default=10800, ge=300, le=10800)
    iterations: int = Field(default=5, ge=1, le=20)
    fights: int = Field(default=10, ge=1, le=40)
    seed: int = Field(default=1, ge=0, le=2**31)
    profession_node: str | None = Field(default=None, max_length=96)
    profession_level: int | None = Field(default=None, ge=1, le=500)


async def config(db: AsyncSession) -> sim.SimulatorConfig:
    return await get_published_balance(db, "simulator", sim.SimulatorConfig)


@asynccontextmanager
async def sandbox(db: AsyncSession) -> AsyncIterator[User]:
    """A rolled-back savepoint with a throwaway, unusable account."""
    sp = await db.begin_nested()
    try:
        user = User(email=f"sim-{uuid.uuid4().hex[:10]}@example.invalid", password_hash="!disabled")  # noqa: S106
        db.add(user)
        await db.flush()
        yield user
    finally:
        await sp.rollback()


async def _zone_for(db: AsyncSession, level: int, code: str | None) -> Zone:
    stmt = select(Zone).where(Zone.status == "published", Zone.deleted_at.is_(None))
    stmt = (
        stmt.where(Zone.code == code) if code else stmt.where(Zone.min_level <= level).order_by(Zone.min_level.desc())
    )
    zone = (await db.execute(stmt.limit(1))).scalar_one_or_none()
    if zone is None:
        raise NotFoundError("Zone not found", code="zone_not_found")
    return zone


async def build_character(
    db: AsyncSession, user: User, p: SimParams, cfg: sim.SimulatorConfig
) -> tuple[Character, list[dict[str, Any]]]:
    race = (await db.execute(select(Race).where(Race.code == p.race))).scalar_one_or_none()
    base = (await db.execute(select(BaseClass).where(BaseClass.code == p.base_class))).scalar_one_or_none()
    if race is None or base is None:
        raise ValidationFailedError("Unknown race or class", code="invalid_reference")
    name = "S" + uuid.uuid4().hex[:11]
    ch = Character(user_id=user.id, name=name, name_normalized=name_key(name), race_id=race.id, base_class_id=base.id,
                   level=p.level, xp=0, unspent_stat_points=(p.level - 1) * 3)  # fmt: skip
    db.add(ch)
    await db.flush()
    profile = cfg.stat_profile.get(base.code) or cfg.stat_profile[base.category]
    plan = await progression.template_points(db, ch, profile, ch.unspent_stat_points)
    await progression.allocate(
        db, character=ch, points=plan, expected_version=ch.version, idempotency_key=uuid.uuid4().hex, mode="template"
    )
    row = await classes.get_progression_row(db, ch, for_update=True)
    if p.specialization:
        spec = (
            await db.execute(select(Specialization).where(Specialization.code == p.specialization))
        ).scalar_one_or_none()
        branch = (
            (await db.execute(select(ClassBranch).where(ClassBranch.code == spec.branch_code))).scalar_one_or_none()
            if spec
            else None
        )
        if spec is None or branch is None or branch.base_class_code != base.code:
            raise ValidationFailedError("Specialization does not belong to the class", code="invalid_reference")
        now = datetime.now(UTC)
        row.branch_code, row.specialization_code, row.promoted_at, row.specialized_at = branch.code, spec.code, now, now
    await classes.sync_milestones(db, ch, row)
    if p.talent_build != "none":
        tcfg = await get_published_balance(db, "talents", TalentConfig)
        trees, nodes = await talents.class_trees(db, base.code)
        tree_codes = [t.code for t in trees]
        focus = [p.talent_build] if p.talent_build in tree_codes else tree_codes
        alloc = sim.greedy_talents(talents.node_defs(nodes), p.level, tcfg, focus)
        for code, rank in alloc.items():
            db.add(CharacterTalentAllocation(character_id=ch.id, node_code=code, rank=rank))
        row.talent_points_spent = sum(alloc.values())
    await db.flush()
    rules = await get_published_balance(db, "item_rules", ItemRules)
    gen = (await get_published_balance(db, "item_studio", ItemStudioConfig)).generator
    tier = (
        p.gear_tier
        if p.gear_tier is not None
        else next((g.tier for g in reversed(rules.tiers) if g.min_level <= p.level), 0)
    )
    return ch, sim.synthetic_gear(cfg, gen, rules, base.code, tier, p.gear_budget_pct)


async def _loot_value(db: AsyncSession, drops: list[dict[str, Any]], cache: dict[tuple[Any, ...], float]) -> float:
    total = 0.0
    for d in drops:
        key = (d["kind"], d.get("ref"), d.get("tier"), d.get("rarity"))
        if key not in cache:
            stmt = select(func.avg(ItemTemplate.vendor_value)).where(ItemTemplate.status == "published")
            if d.get("ref"):
                stmt = stmt.where(ItemTemplate.code == d["ref"])
            else:
                if d.get("tier") is not None:
                    stmt = stmt.where(ItemTemplate.tier == d["tier"])
                if d.get("rarity"):
                    stmt = stmt.where(ItemTemplate.rarity == d["rarity"])
            cache[key] = float((await db.execute(stmt)).scalar_one() or 0)
        total += cache[key] * int(d.get("qty", 1))
    return total


def fight_metrics(snap: afk_engine.AfkSnapshot, *, fights: int, seed: int) -> dict[str, float]:
    """Direct combat samples in the snapshot's zone: DPS/HPS, effective damage taken, support contribution."""
    rules = validate_rules(list(snap.rules))
    enemy_sel = rules_by_code_selector(enemy_rules(snap.zone))
    acc = {"elapsed": 0.0, "dealt": 0.0, "healed": 0.0, "taken": 0.0, "support": 0.0, "wins": 0.0, "kill_time": 0.0}
    for i in range(fights):
        fs = derive_seed(seed, "simfight", i)
        enc = generate_encounter(
            snap.zone,
            Rng(derive_seed(fs, "encounter")),
            snap.character_level,
            power_percent=snap.risk.enemy_power_percent,
        )
        data = CombatInput(players=(snap.player,), enemies=enc.enemies, strategy=snap.strategy, seed=fs)
        r = simulate(data, snap.combat, selector=rule_selector(rules), enemy_selector=enemy_sel)
        me = r.combatants[0]
        acc["elapsed"] += r.elapsed_s
        acc["dealt"] += me.damage_dealt
        acc["healed"] += me.healing_done
        acc["taken"] += max(0.0, me.damage_taken - me.shield_absorbed)
        acc["support"] += me.healing_done + me.shield_granted + me.damage_prevented
        if r.outcome == "win":
            acc["wins"] += 1
            acc["kill_time"] += r.elapsed_s
    t = max(acc["elapsed"], 1e-9)
    return {
        "dps": round(acc["dealt"] / t, 3),
        "hps": round(acc["healed"] / t, 3),
        "effective_damage_taken_per_s": round(acc["taken"] / t, 3),
        "support_contribution_per_s": round(acc["support"] / t, 3),
        "win_rate": round(acc["wins"] / fights, 3),
        "avg_kill_time_s": round(acc["kill_time"] / acc["wins"], 3) if acc["wins"] else float("inf"),
    }


async def _snapshot(
    db: AsyncSession, ch: Character, gear: list[dict[str, Any]], zone: Zone, p: SimParams
) -> afk_engine.AfkSnapshot:
    cfg = await get_published_balance(db, "afk", afk_engine.AfkBalance)
    snap, _ = await afk.build_snapshot(db, ch, cfg=cfg, zone_code=zone.code, duration_s=p.duration_s, risk_level=p.risk,
                                       started=datetime.now(UTC), prior={}, extra_effects=gear)  # fmt: skip
    return snap


async def run(db: AsyncSession, p: SimParams) -> dict[str, Any]:
    cfg = await config(db)
    p = p.model_copy(
        update={
            "iterations": min(p.iterations, cfg.limits.max_iterations),
            "fights": min(p.fights, cfg.limits.max_fights),
        }
    )
    zone = await _zone_for(db, p.level, p.zone)
    async with sandbox(db) as user:
        ch, gear = await build_character(db, user, p, cfg)
        snap = await _snapshot(db, ch, gear, zone, p)
        hours = p.duration_s / 3600
        cache: dict[tuple[Any, ...], float] = {}
        per_iteration = []
        for i in range(p.iterations):
            seed = derive_seed(p.seed, "afk", i) & ((1 << 62) - 1)
            res = afk_engine.resolve(snap, seed, p.duration_s)
            loot = await _loot_value(db, res["drops"], cache)
            per_iteration.append({
                "iteration": i, "seed": seed, "fights": res["fights"], "kills": res["kills"], "deaths": res["deaths"],
                "xp": res["xp"], "gold": res["gold"], "potions_used": res["potions_used"], "loot_value": round(loot, 2),
                "kills_per_hour": round(res["kills"] / hours, 2), "xp_per_hour": round(res["xp"] / hours, 2),
                "gold_per_hour": round(res["gold"] / hours, 2), "loot_value_per_hour": round(loot / hours, 2),
                "potions_per_hour": round(res["potions_used"] / hours, 3),
                "death_probability": round(res["deaths"] / res["fights"], 4) if res["fights"] else 0.0,
            })  # fmt: skip
        combat = fight_metrics(snap, fights=p.fights, seed=p.seed)
        profession = await _profession_yield(db, p) if p.profession_node else None
        stats = {
            k: round(v, 2)
            for k, v in snap.player.stats.items()
            if k in ("max_hp", "attack_power", "spell_power", "armor", "crit_chance")
        }
    keys = (
        "kills_per_hour",
        "xp_per_hour",
        "gold_per_hour",
        "loot_value_per_hour",
        "potions_per_hour",
        "death_probability",
    )
    return {
        "params": p.model_dump(),
        "zone": zone.code,
        "gear_effects": gear,
        "stats": stats,
        "metrics": {k: sim.summarize([r[k] for r in per_iteration]) for k in keys},
        "combat": combat,
        "profession": profession,
        "per_iteration": per_iteration,
    }


async def _profession_yield(db: AsyncSession, p: SimParams) -> dict[str, Any]:
    node = (await db.execute(select(GatheringNode).where(GatheringNode.code == p.profession_node))).scalar_one_or_none()
    if node is None:
        raise NotFoundError("Gathering node not found", code="invalid_gathering_node")
    ccfg = await get_published_balance(db, "crafting", CraftingConfig)
    out = resolve_gathering(
        ccfg,
        entries=node.entries,
        node_tier=node.tier,
        actions_per_hour=node.actions_per_hour or ccfg.gathering.default_actions_per_hour,
        segments=[(3600.0, 1.0)],
        speed_pct=0,
        yield_pct=100,
        rare_find_pct=0,
        seed=p.seed,
    )
    value = await _loot_value(db, [{"kind": "material", "ref": k, "qty": v} for k, v in out["materials"].items()], {})
    return {
        "node": node.code,
        "profession": node.profession_code,
        "materials_per_hour": out["materials"],
        "actions_per_hour": out["actions"],
        "xp_per_hour": out["xp"],
        "value_per_hour": round(value, 2),
    }


def to_csv(result: dict[str, Any]) -> str:
    buf = io.StringIO()
    rows = result["per_iteration"]
    w = csv.DictWriter(buf, fieldnames=list(rows[0]) if rows else ["iteration"])
    w.writeheader()
    for r in rows:
        w.writerow(r)
    buf.write("\n")
    buf.write("metric,value\n")
    for k, v in result["combat"].items():
        buf.write(f"{k},{v}\n")
    return buf.getvalue()


# --------------------------------------------------------------------------- balance checker
async def _speed(db: AsyncSession, user: User, p: SimParams, cfg: sim.SimulatorConfig, zone: Zone) -> dict[str, float]:
    ch, gear = await build_character(db, user, p, cfg)
    snap = await _snapshot(db, ch, gear, zone, p)
    m = fight_metrics(snap, fights=p.fights, seed=p.seed)
    m["kill_speed"] = round(1 / m["avg_kill_time_s"], 5) if m["avg_kill_time_s"] not in (0, float("inf")) else 0.0
    return m


async def check(
    db: AsyncSession, *, level: int, sections: tuple[str, ...], fights: int | None = None
) -> dict[str, Any]:
    cfg = await config(db)
    c = cfg.checker
    n = min(fights or c.fights, cfg.limits.max_fights)
    report: dict[str, Any] = {"level": level, "fights": n, "warnings": [], "sections": {}}
    warn = report["warnings"].append
    class_rows = list(
        (
            await db.execute(select(BaseClass).where(BaseClass.status == "published").order_by(BaseClass.sort_order))
        ).scalars()
    )
    races = list((await db.execute(select(Race).where(Race.status == "published").order_by(Race.code))).scalars())
    zone = await _zone_for(db, level, None)
    base = {"level": level, "fights": n, "duration_s": 3600, "iterations": 1, "seed": 7}
    rows: list[dict[str, Any]]
    async with sandbox(db) as user:
        if "support" in sections:
            rows = []
            for b in class_rows:
                m = await _speed(db, user, SimParams(base_class=b.code, **base), cfg, zone)
                rows.append({"class": b.code, "category": b.category, **m})
            dps = [r["kill_speed"] for r in rows if r["category"] == "combat" and r["kill_speed"]]
            ref = sum(dps) / len(dps) if dps else 0.0
            lo, hi = c.support_band_pct
            for r in rows:
                r["vs_dps_pct"] = round(100 * r["kill_speed"] / ref, 1) if ref else 0.0
                if r["category"] == "support" and not lo <= r["vs_dps_pct"] <= hi:
                    warn(
                        {
                            "section": "support",
                            "subject": r["class"],
                            "message": f"solo kill speed {r['vs_dps_pct']}% of pure DPS (target {lo}-{hi}%)",
                        }
                    )
            report["sections"]["support"] = rows
        if "racial" in sections:
            rows = []
            for cls in ("warrior", "mage", "cleric"):
                per: list[dict[str, Any]] = []
                for race in races:
                    m = await _speed(db, user, SimParams(base_class=cls, race=race.code, **base), cfg, zone)
                    per.append({"class": cls, "race": race.code, **m})
                ref = sorted(x["kill_speed"] for x in per)[len(per) // 2]
                for x in per:
                    x["delta_pct"] = sim.pct_delta(x["kill_speed"], ref)
                    if abs(x["delta_pct"]) > c.racial_warn_pct:
                        warn(
                            {
                                "section": "racial",
                                "subject": f"{x['race']}/{cls}",
                                "message": f"racial combat advantage {x['delta_pct']}% "
                                f"(target ≤{c.racial_target_pct}%, warn >{c.racial_warn_pct}%)",
                            }
                        )
                rows += per
            report["sections"]["racial"] = rows
        if "specializations" in sections:
            lvl = max(level, 300)
            rows = []
            for spec in (
                await db.execute(
                    select(Specialization).where(Specialization.status == "published").order_by(Specialization.code)
                )
            ).scalars():
                branch = (
                    await db.get(ClassBranch, spec.branch_code)
                    if False
                    else (
                        await db.execute(select(ClassBranch).where(ClassBranch.code == spec.branch_code))
                    ).scalar_one()
                )
                m = await _speed(
                    db,
                    user,
                    SimParams(base_class=branch.base_class_code, specialization=spec.code, **{**base, "level": lvl}),
                    cfg,
                    await _zone_for(db, lvl, None),
                )
                rows.append({"specialization": spec.code, "class": branch.base_class_code, **m})
            _dominance(
                rows,
                "specialization",
                c.dominance_warn_pct,
                warn,
                group="class_category",
                cats={b.code: b.category for b in class_rows},
            )
            report["sections"]["specializations"] = rows
        if "talents" in sections:
            lvl = max(level, 100)
            rows = []
            for b in class_rows:
                trees, _ = await talents.class_trees(db, b.code)
                for t in trees:
                    m = await _speed(
                        db,
                        user,
                        SimParams(base_class=b.code, talent_build=t.code, **{**base, "level": lvl}),
                        cfg,
                        await _zone_for(db, lvl, None),
                    )
                    rows.append({"class": b.code, "tree": t.code, **m})
            for b in class_rows:
                mine = [r for r in rows if r["class"] == b.code and r["kill_speed"]]
                if len(mine) > 1:
                    med = sorted(r["kill_speed"] for r in mine)[len(mine) // 2]
                    for r in mine:
                        d = sim.pct_delta(r["kill_speed"], med)
                        r["delta_pct"] = d
                        if d > c.dominance_warn_pct:
                            warn(
                                {
                                    "section": "talents",
                                    "subject": f"{b.code}/{r['tree']}",
                                    "message": f"tree {d}% faster than the class median",
                                }
                            )
            report["sections"]["talents"] = rows
    if "items" in sections:
        report["sections"]["items"] = await _item_checks(db, warn)
    return report


def _dominance(
    rows: list[dict[str, Any]], key: str, limit: float, warn: Any, *, group: str, cats: dict[str, str]
) -> None:
    by: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        by.setdefault(cats.get(r["class"], "combat"), []).append(r)
    for _, items in by.items():
        speeds = sorted(r["kill_speed"] for r in items if r["kill_speed"])
        if not speeds:
            continue
        med = speeds[len(speeds) // 2]
        for r in items:
            r["delta_pct"] = sim.pct_delta(r["kill_speed"], med)
            if r["delta_pct"] > limit:
                warn(
                    {
                        "section": key,
                        "subject": r[key],
                        "message": f"{r['delta_pct']}% above the {group.replace('_', ' ')} median",
                    }
                )


async def _item_checks(db: AsyncSession, warn: Any) -> dict[str, Any]:
    rules = await get_published_balance(db, "item_rules", ItemRules)
    gen = (await get_published_balance(db, "item_studio", ItemStudioConfig)).generator
    from app.services.catalog import catalog_config

    cat_cfg = catalog_config()
    rows = list(
        (
            await db.execute(
                select(ItemTemplate).where(ItemTemplate.status == "published", ItemTemplate.slot.is_not(None))
            )
        ).scalars()
    )
    as_rows = [
        {
            "code": t.code,
            "kind": t.category,
            "data": {
                "tier": t.tier,
                "slot": t.slot,
                "family": t.family or t.weapon_family or t.armor_family,
                "base_stats": t.base_stats,
            },
        }
        for t in rows
    ]
    outliers = catalog_engine.outliers(cat_cfg, as_rows, dict(gen.slot_multipliers))
    impossible = []
    for t in rows:
        reqs = (t.requirements or {}).get("stats", {})
        errors = [msg for level, msg in requirement_problems(rules, t.min_level, reqs) if level == "error"]
        if errors:
            impossible.append({"code": t.code, "min_level": t.min_level, "requirements": reqs, "problem": errors[0]})
    for o in outliers[:50]:
        warn(
            {
                "section": "items",
                "subject": o["code"],
                "message": f"T{o['tier']} {o['category']} power ×{o['ratio']} of the tier median",
            }
        )
    for i in impossible[:50]:
        warn({"section": "items", "subject": i["code"], "message": f"impossible requirement: {i['problem']}"})
    return {"checked": len(rows), "outliers": outliers, "impossible_requirements": impossible}
