"""Race read models + providers plugging racial effects into progression (no race-specific branching)."""

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.game_engine.effects import ProgressionModifier, validate_effect
from app.game_engine.stat_calculator import Contribution, contribution_from_effects
from app.localization.service import resolve_text_map
from app.models.character import Character
from app.models.race import Race
from app.services import progression


async def published_races(db: AsyncSession) -> list[Race]:
    return list(
        (
            await db.execute(
                select(Race)
                .where(Race.status == "published", Race.deleted_at.is_(None))
                .order_by(Race.sort_order, Race.id)
            )
        ).scalars()
    )


def stat_label_keys(effects: list[dict[str, Any]]) -> set[str]:
    keys: set[str] = set()
    for e in effects:
        p = e.get("params", {})
        if p.get("stat"):
            keys.add(f"stat.{p['stat'].lower()}.name")
        for nested in p.get("effects", []) or []:
            keys |= stat_label_keys([nested])
    return keys


async def race_cards(db: AsyncSession, locale: str) -> list[dict[str, Any]]:
    races = await published_races(db)
    keys: set[str] = set()
    for r in races:
        keys |= {r.name_key, r.description_key or "", r.trait_name_key, r.trait_description_key, r.title_key}
        keys |= stat_label_keys(r.effects)
    text = await resolve_text_map(db, sorted(k for k in keys if k), locale)
    return [
        {
            "id": r.id,
            "code": r.code,
            "name": text[r.name_key],
            "description": text.get(r.description_key or "", ""),
            "trait_name": text[r.trait_name_key],
            "trait_description": text[r.trait_description_key],
            "title": text[r.title_key],
            "identity": r.identity,
            "affinity": r.affinity,
            "effects": r.effects,
            "labels": {k: text[k] for k in stat_label_keys(r.effects)},
        }
        for r in races
    ]


async def race_for(db: AsyncSession, character: Character) -> Race | None:
    return await db.get(Race, character.race_id)


async def race_contributions(db: AsyncSession, character: Character) -> list[Contribution]:
    race = await race_for(db, character)
    return [contribution_from_effects("race", race.code, race.effects)] if race else []


async def race_respec_discount(db: AsyncSession, character: Character) -> tuple[float, int | None] | None:
    race = await race_for(db, character)
    if race is None:
        return None
    for e in race.effects:
        params = validate_effect(e)
        if isinstance(params, ProgressionModifier) and params.kind == "respec_cost":
            return -params.percent, params.limit_points
    return None


progression.CONTRIBUTION_PROVIDERS.append(race_contributions)
progression.RESPEC_DISCOUNT_PROVIDERS.append(race_respec_discount)
