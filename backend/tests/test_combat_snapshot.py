import zlib

from sqlalchemy import select

from app.db.session import get_sessionmaker
from app.game_engine.combat.engine import simulate
from app.game_engine.combat.models import CombatInput
from app.models.character import Character
from app.models.classes import ClassBranch, Specialization
from app.services import classes, combat_snapshot
from tests.engine.factories import enemy
from tests.test_classes import _class_id


async def test_snapshot_contains_build_effects_and_abilities(make_client, make_character) -> None:  # type: ignore[no-untyped-def]
    u = await make_client()
    cid = await make_character(u.user_id, level=320, base_class_id=await _class_id("warrior"))
    await u.http.post(f"/api/v1/characters/{cid}/class/promote", json={"branch_code": "reaver"})
    await u.http.post(f"/api/v1/characters/{cid}/class/specialize", json={"specialization_code": "berserker"})
    async with get_sessionmaker()() as s:
        ch = await s.get(Character, cid)
        assert ch is not None
        snap = await combat_snapshot.character_snapshot(s, ch)
    types = [e["effect_type"] for e in snap.effects]
    assert "SCALING_BONUS" in types  # berserker Blood Rage
    assert any(e["effect_type"] == "DAMAGE_MULTIPLIER" and e["params"].get("condition") for e in snap.effects)
    assert not any(e["effect_type"] in ("STAT_FLAT", "STAT_PERCENT") for e in snap.effects)  # baked into stats
    assert {a.code for a in snap.abilities} >= {"shield_slam", "execution", "whirlwind"}
    assert snap.primary_resource == "rage" and snap.power_stat == "attack_power"


async def test_solo_accord_boosts_support_only_when_alone(make_client, make_character) -> None:  # type: ignore[no-untyped-def]
    u = await make_client()
    cid = await make_character(u.user_id, level=100, base_class_id=await _class_id("cleric"))
    async with get_sessionmaker()() as s:
        ch = await s.get(Character, cid)
        assert ch is not None
        solo = await combat_snapshot.character_snapshot(s, ch, party_size=1)
        grouped = await combat_snapshot.character_snapshot(s, ch, party_size=3)
    heal_power = grouped.stats["healing_power"] + grouped.stats["shield_power"]
    assert solo.stats["spell_power"] == grouped.stats["spell_power"] + heal_power * 0.35
    assert solo.power_stat == "spell_power"


async def test_every_specialization_simulates_with_real_content(make_client, make_character) -> None:  # type: ignore[no-untyped-def]
    """Robustness: every published effect definition must be executable by the engine."""
    u = await make_client()
    async with get_sessionmaker()() as s:
        specs = list(
            (
                await s.execute(
                    select(Specialization.code, ClassBranch.code, ClassBranch.base_class_code)
                    .join(ClassBranch, ClassBranch.code == Specialization.branch_code)
                    .where(Specialization.status == "published", Specialization.deleted_at.is_(None))
                )
            ).all()
        )
    assert len(specs) == 40
    for spec, branch, cls in specs:
        cid = await make_character(u.user_id, level=700, base_class_id=await _class_id(cls))
        async with get_sessionmaker()() as s:
            ch = await s.get(Character, cid)
            assert ch is not None
            row = await classes.get_progression_row(s, ch, for_update=True)
            row.branch_code, row.specialization_code = branch, spec
            await classes.sync_milestones(s, ch, row)
            await s.commit()
            snap = await combat_snapshot.character_snapshot(s, ch)
        result = simulate(
            CombatInput(
                players=(snap,),
                enemies=(
                    enemy(
                        "e0",
                        level=700,
                        stats={"max_hp": 20000, "attack_power": 400, "armor": 1500, "magic_resist": 800},
                    ),
                ),
                seed=zlib.crc32(spec.encode()),
            )
        )
        assert result.outcome in ("win", "loss", "timeout"), spec
        assert result.combatants[0].damage_dealt > 0, spec
