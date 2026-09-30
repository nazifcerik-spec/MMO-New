"""Measure solo kill speed / sustain per class at a level with template stats (support parity check).

Usage: python -m scripts.balance_probe --level 100 --fights 30
Creates throwaway characters inside a transaction that is rolled back (no persistent writes)."""

import argparse
import asyncio
import json
import uuid
import zlib
from typing import Any

from sqlalchemy import select

from app.content.names import name_key
from app.db.session import dispose_engine, get_sessionmaker
from app.game_engine.combat.engine import simulate
from app.game_engine.combat.models import CombatInput
from app.game_engine.combat.rules import rule_selector
from app.game_engine.combat.training import TrainingEncounter, training_pack
from app.game_engine.rng import Rng
from app.game_engine.world import enemy_rules, generate_encounter, rules_by_code_selector
from app.models.auth import User
from app.models.character import Character
from app.models.classes import BaseClass
from app.models.race import Race
from app.services import afk_profiles, combat_snapshot, progression, world
from app.services import plugins as _plugins  # noqa: F401
from app.services.content.types.balance import get_published_balance

PROFILE_BY_CATEGORY = {"combat": "physical_dps", "support": "hybrid_support"}
CASTER = {"mage": "caster_dps"}


async def probe(level: int, fights: int, zone: str | None = None, boss: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {}
    async with get_sessionmaker()() as db:
        user = User(email=f"probe-{uuid.uuid4().hex[:8]}@example.com", password_hash="!disabled")  # noqa: S106 - throwaway, rolled back, unusable hash
        db.add(user)
        await db.flush()
        race = (await db.execute(select(Race).where(Race.code == "human"))).scalar_one()
        cfg = await combat_snapshot.load_combat_config(db)
        training = await get_published_balance(db, "training_encounter", TrainingEncounter)
        bundle = await world.load_bundle(db, zone) if zone else None
        enemy_sel = rules_by_code_selector(enemy_rules(bundle)) if bundle else None
        for base in (await db.execute(select(BaseClass).order_by(BaseClass.sort_order))).scalars():
            name = "P" + uuid.uuid4().hex[:10]
            ch = Character(
                user_id=user.id,
                name=name,
                name_normalized=name_key(name),
                race_id=race.id,
                base_class_id=base.id,
                level=level,
                xp=0,
                unspent_stat_points=(level - 1) * 3,
            )
            db.add(ch)
            await db.flush()
            prof_code = CASTER.get(base.code, PROFILE_BY_CATEGORY[base.category])
            plan = await progression.template_points(db, ch, prof_code, ch.unspent_stat_points)
            await progression.allocate(
                db,
                character=ch,
                points=plan,
                expected_version=ch.version,
                idempotency_key=uuid.uuid4().hex,
                mode="template",
            )
            row = await afk_profiles.get_profile(db, ch)
            rules, extra = await afk_profiles.resolved_rules(db, row, encounter_type="normal")
            snap = afk_profiles.with_extra_effects(await combat_snapshot.character_snapshot(db, ch), extra)
            times, taken, wins = [], [], 0
            for i in range(fights):
                seed = zlib.crc32(f"{base.code}:{i}".encode())
                enemies = (
                    generate_encounter(bundle, Rng(seed), level, force_boss=boss).enemies
                    if bundle
                    else training_pack(training, level)
                )
                r = simulate(
                    CombatInput(
                        players=(snap,),
                        enemies=enemies,
                        strategy=afk_profiles.strategy_for(row, 0),
                        seed=seed,
                    ),
                    cfg,
                    selector=rule_selector(rules),
                    enemy_selector=enemy_sel,
                )
                wins += r.outcome == "win"
                times.append(r.elapsed_s)
                me = r.combatants[0]
                taken.append(me.damage_taken - me.shield_absorbed - me.healing_done)
            out[base.code] = {
                "category": base.category,
                "win_rate": wins / fights,
                "avg_time": sum(times) / fights,
                "net_damage_taken_pct": 100 * sum(taken) / fights / snap.stats["max_hp"],
            }
        await db.rollback()
    combat = [v["avg_time"] for v in out.values() if v["category"] == "combat"]
    ref = sum(combat) / len(combat)
    for v in out.values():
        v["kill_speed_vs_dps"] = round(ref / v["avg_time"], 3)
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--level", type=int, default=100)
    ap.add_argument("--fights", type=int, default=30)
    ap.add_argument("--zone")
    ap.add_argument("--boss", action="store_true")
    a = ap.parse_args()

    async def main() -> None:
        res = await probe(a.level, a.fights, a.zone, a.boss)
        await dispose_engine()
        print(json.dumps(res, indent=1))

    asyncio.run(main())
