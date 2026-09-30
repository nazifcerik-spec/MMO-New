"""Profession service: per-character progress (independent of character XP), exactly-once profession XP,
Specialist Licenses (max 3, free first activations, cooldown + gold for swaps), specializations, grandmaster
titles, and profession modifiers aggregated from the effect registry (race, gear, specialization, providers)."""

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError, ValidationFailedError
from app.game_engine import professions as rules
from app.localization.service import resolve_text_map
from app.models.character import Character
from app.models.items import ItemInstance
from app.models.professions import (
    CharacterProfession,
    CharacterProfessionMeta,
    CharacterTitle,
    Profession,
    ProfessionSpecialization,
    ProfessionXpEvent,
)
from app.models.race import Race
from app.services import audit, items, progression, wallet
from app.services.content.types.balance import get_published_balance

# Extra PROFESSION_YIELD_MOD sources (titles, events, housing…): async (db, character) -> list[effect]
EFFECT_PROVIDERS: list[Any] = []


def now_utc() -> datetime:
    return datetime.now(UTC)


async def config(db: AsyncSession) -> rules.ProfessionConfig:
    return await get_published_balance(db, "professions", rules.ProfessionConfig)


async def catalog(db: AsyncSession) -> tuple[list[Profession], dict[str, list[ProfessionSpecialization]]]:
    profs = list(
        (
            await db.execute(
                select(Profession)
                .where(Profession.status == "published", Profession.deleted_at.is_(None))
                .order_by(Profession.sort_order, Profession.code)
            )
        ).scalars()
    )
    specs: dict[str, list[ProfessionSpecialization]] = {}
    for s in (
        await db.execute(
            select(ProfessionSpecialization)
            .where(ProfessionSpecialization.status == "published", ProfessionSpecialization.deleted_at.is_(None))
            .order_by(ProfessionSpecialization.sort_order)
        )
    ).scalars():
        specs.setdefault(s.profession_code, []).append(s)
    return profs, specs


async def _profession(db: AsyncSession, code: str) -> Profession:
    p = (
        await db.execute(select(Profession).where(Profession.code == code, Profession.status == "published"))
    ).scalar_one_or_none()
    if p is None:
        raise NotFoundError("Profession not found", code="profession_not_found")
    return p


async def rows(db: AsyncSession, character_id: int, *, for_update: bool = False) -> dict[str, CharacterProfession]:
    profs, _ = await catalog(db)
    await db.execute(
        insert(CharacterProfession)
        .values([{"character_id": character_id, "profession_code": p.code} for p in profs])
        .on_conflict_do_nothing(index_elements=["character_id", "profession_code"])
    )
    stmt = select(CharacterProfession).where(CharacterProfession.character_id == character_id)
    if for_update:
        stmt = stmt.with_for_update()
    return {r.profession_code: r for r in (await db.execute(stmt)).scalars()}


async def _meta(db: AsyncSession, character_id: int) -> CharacterProfessionMeta:
    await db.execute(
        insert(CharacterProfessionMeta)
        .values(character_id=character_id)
        .on_conflict_do_nothing(index_elements=["character_id"])
    )
    return (
        await db.execute(
            select(CharacterProfessionMeta)
            .where(CharacterProfessionMeta.character_id == character_id)
            .with_for_update()
        )
    ).scalar_one()


# --------------------------------------------------------------------------- modifiers
async def profession_effects(db: AsyncSession, character: Character) -> list[dict[str, Any]]:
    race = await db.get(Race, character.race_id)
    out: list[dict[str, Any]] = list(race.effects if race else [])
    out += await items.equipment_effects(db, character)
    progress = await rows(db, character.id)
    specs = [r.specialization_code for r in progress.values() if r.licensed and r.specialization_code]
    if specs:
        for s in (
            await db.execute(select(ProfessionSpecialization).where(ProfessionSpecialization.code.in_(specs)))
        ).scalars():
            out += s.effects
    for p in EFFECT_PROVIDERS:
        out += await p(db, character)
    return out


async def tool_tier(db: AsyncSession, character: Character, tool_kind: str) -> int | None:
    tool = (
        await db.execute(
            select(ItemInstance).where(
                ItemInstance.owner_character_id == character.id,
                ItemInstance.location == "equipped",
                ItemInstance.equipped_slot == "tool",
            )
        )
    ).scalar_one_or_none()
    if tool is None or (tool.durability_max and tool.durability == 0):
        return None
    data = await items.revision_data(db, tool.template_code, tool.template_revision_no)
    return int(data["tier"]) if data.get("subcategory") == tool_kind else None


async def node_check(db: AsyncSession, character: Character, code: str, node_tier: int) -> dict[str, Any]:
    """Everything a gathering/crafting action needs: access, tool yield, stat bonuses and modifiers."""
    cfg = await config(db)
    prof = await _profession(db, code)
    row = (await rows(db, character.id))[code]
    stats = {k: v for k, v in (await progression.stat_sheet(db, character)).finals().items() if k.isupper()}
    tier = await tool_tier(db, character, prof.tool_kind)
    need = rules.node_level_required(cfg, node_tier)
    return {
        "profession": code,
        "level": row.level,
        "node_tier": node_tier,
        "required_level": need,
        "accessible": row.level >= need,
        "tool_tier": tier,
        "tool_yield_pct": rules.tool_yield_pct(cfg, tier, node_tier),
        "stat_bonuses": rules.stat_bonuses(cfg, stats, prof.stats),
        "modifiers": rules.yield_modifiers(await profession_effects(db, character), code),
    }


# --------------------------------------------------------------------------- XP
async def grant_xp(
    db: AsyncSession,
    *,
    character: Character,
    profession_code: str,
    amount: int,
    idempotency_key: str,
    source_type: str,
    apply_bonus: bool = True,
) -> dict[str, Any]:
    """Exactly-once profession XP (independent of character XP). Caller holds the character row lock."""
    if amount < 0:
        raise ValidationFailedError("XP must be non-negative", code="invalid_amount")
    prior = (
        await db.execute(
            select(ProfessionXpEvent).where(
                ProfessionXpEvent.character_id == character.id, ProfessionXpEvent.idempotency_key == idempotency_key
            )
        )
    ).scalar_one_or_none()
    if prior is not None:
        return {**prior.result, "replayed": True}
    cfg = await config(db)
    await _profession(db, profession_code)
    row = (await rows(db, character.id, for_update=True))[profession_code]
    bonus = 0.0
    if apply_bonus:
        bonus = rules.yield_modifiers(await profession_effects(db, character), profession_code)["xp"]
    gain = round(amount * (1 + bonus / 100))
    before = row.level
    res = rules.apply_xp(cfg, row.level, row.xp, gain, licensed=row.licensed)
    row.level, row.xp = res.level, res.xp
    title = None
    if res.reached_cap:
        title = await _award_title(db, character, profession_code)
    result = {
        "profession": profession_code,
        "xp_gained": gain,
        "level_before": before,
        "level_after": res.level,
        "levels_gained": res.levels_gained,
        "capped_by_license": res.capped_by_license,
        "title": title,
    }
    db.add(
        ProfessionXpEvent(
            character_id=character.id,
            profession_code=profession_code,
            idempotency_key=idempotency_key,
            amount=gain,
            level_before=before,
            level_after=res.level,
            source_type=source_type,
            result=result,
        )
    )
    await db.flush()
    return {**result, "replayed": False}


async def _award_title(db: AsyncSession, character: Character, profession_code: str) -> str:
    code = f"grandmaster_{profession_code}"
    await db.execute(
        insert(CharacterTitle)
        .values(
            character_id=character.id,
            title_code=code,
            title_key=f"profession.{profession_code}.title",
            source="profession",
        )
        .on_conflict_do_nothing(index_elements=["character_id", "title_code"])
    )
    return code


# --------------------------------------------------------------------------- licenses & specializations
async def set_license(
    db: AsyncSession,
    *,
    character: Character,
    code: str,
    active: bool,
    idempotency_key: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    cfg = await config(db)
    now = now or now_utc()
    await _profession(db, code)
    progress = await rows(db, character.id, for_update=True)
    row = progress[code]
    meta = await _meta(db, character.id)
    if row.licensed == active:
        return {"profession": code, "licensed": active, "cost_gold": 0, "changed": False}
    cost = 0
    if active:
        if sum(r.licensed for r in progress.values()) >= cfg.license.max_active:
            raise ConflictError(
                f"At most {cfg.license.max_active} Specialist Licenses can be active", code="license_limit"
            )
        if meta.license_activations >= cfg.license.free_activations:
            if meta.last_license_change_at is not None:
                ready = meta.last_license_change_at + timedelta(seconds=cfg.license.swap_cooldown_s)
                if now < ready:
                    raise ConflictError(
                        "License change is on cooldown",
                        code="license_cooldown",
                        details={"ready_at": ready.isoformat()},
                    )
            cost = rules.swap_cost(cfg, row.level)
            if cost:
                await wallet.change_gold(
                    db,
                    character_id=character.id,
                    delta=-cost,
                    reason="license_swap",
                    idempotency_key=f"license:{idempotency_key}",
                    ref_type="profession",
                    ref_id=code,
                )
        meta.license_activations += 1
        row.licensed, row.licensed_at = True, now
    else:
        row.licensed = False
    meta.last_license_change_at = now
    await db.flush()
    await audit.record(
        db,
        actor_id=character.user_id,
        action="profession.license",
        entity_type="character",
        entity_id=character.id,
        meta={"profession": code, "active": active, "cost_gold": cost},
    )
    return {"profession": code, "licensed": active, "cost_gold": cost, "changed": True}


async def specialize(
    db: AsyncSession, *, character: Character, code: str, specialization_code: str, idempotency_key: str
) -> dict[str, Any]:
    cfg = await config(db)
    row = (await rows(db, character.id, for_update=True))[code]
    spec = (
        await db.execute(
            select(ProfessionSpecialization).where(
                ProfessionSpecialization.code == specialization_code,
                ProfessionSpecialization.profession_code == code,
                ProfessionSpecialization.status == "published",
            )
        )
    ).scalar_one_or_none()
    if spec is None:
        raise ValidationFailedError("Unknown specialization for this profession", code="invalid_specialization")
    if row.level < cfg.specialization_level:
        raise ConflictError(f"Specialization unlocks at level {cfg.specialization_level}", code="specialization_locked")
    if not row.licensed:
        raise ConflictError("A Specialist License is required", code="license_required")
    if row.specialization_code == spec.code:
        return {"profession": code, "specialization": spec.code, "cost_gold": 0, "changed": False}
    cost = cfg.license.respecialize_cost_gold if row.specialization_code else 0
    if cost:
        await wallet.change_gold(
            db,
            character_id=character.id,
            delta=-cost,
            reason="profession_respec",
            idempotency_key=f"prof_spec:{idempotency_key}",
            ref_type="profession",
            ref_id=code,
        )
    row.specialization_code, row.specialized_at = spec.code, now_utc()
    await db.flush()
    await audit.record(
        db,
        actor_id=character.user_id,
        action="profession.specialize",
        entity_type="character",
        entity_id=character.id,
        meta={"profession": code, "specialization": spec.code, "cost_gold": cost},
    )
    return {"profession": code, "specialization": spec.code, "cost_gold": cost, "changed": True}


# --------------------------------------------------------------------------- views
async def catalog_view(db: AsyncSession, locale: str) -> list[dict[str, Any]]:
    profs, specs = await catalog(db)
    keys = [k for p in profs for k in (p.name_key, p.title_key)] + [s.name_key for v in specs.values() for s in v]
    text = await resolve_text_map(db, keys, locale)
    return [
        {
            "code": p.code,
            "name": text[p.name_key],
            "type": p.type,
            "tool_kind": p.tool_kind,
            "stats": p.stats,
            "title": text[p.title_key],
            "specializations": [
                {"code": s.code, "name": text[s.name_key], "effects": s.effects} for s in specs.get(p.code, [])
            ],
        }
        for p in profs
    ]


async def character_view(db: AsyncSession, character: Character, locale: str) -> dict[str, Any]:
    cfg = await config(db)
    catalog_rows = await catalog_view(db, locale)
    progress = await rows(db, character.id)
    meta = (
        await db.execute(select(CharacterProfessionMeta).where(CharacterProfessionMeta.character_id == character.id))
    ).scalar_one_or_none()
    effects = await profession_effects(db, character)
    stats = {k: v for k, v in (await progression.stat_sheet(db, character)).finals().items() if k.isupper()}
    rank_text = await resolve_text_map(db, [f"profession_rank.{r.code}.name" for r in cfg.ranks], locale)
    titles = list(
        (
            await db.execute(select(CharacterTitle.title_code).where(CharacterTitle.character_id == character.id))
        ).scalars()
    )
    activations = meta.license_activations if meta else 0
    cooldown_until = None
    if meta and meta.last_license_change_at and activations >= cfg.license.free_activations:
        ready = meta.last_license_change_at + timedelta(seconds=cfg.license.swap_cooldown_s)
        cooldown_until = ready.isoformat() if ready > now_utc() else None
    out = []
    for p in catalog_rows:
        r = progress[p["code"]]
        rank = rules.rank_for(cfg, r.level)
        out.append(
            {
                **p,
                "level": r.level,
                "xp": r.xp,
                "xp_to_next": rules.xp_to_next(cfg, r.level),
                "rank": rank,
                "rank_name": rank_text[f"profession_rank.{rank}.name"],
                "licensed": r.licensed,
                "specialization_code": r.specialization_code,
                "level_cap_now": cfg.level_cap if r.licensed else cfg.unlicensed_level_cap,
                "stat_bonuses": rules.stat_bonuses(cfg, stats, p["stats"]),
                "modifiers": rules.yield_modifiers(effects, p["code"]),
                "swap_cost_gold": 0 if activations < cfg.license.free_activations else rules.swap_cost(cfg, r.level),
                "title_earned": f"grandmaster_{p['code']}" in titles,
            }
        )
    return {
        "professions": out,
        "licenses": {
            "active": sum(r.licensed for r in progress.values()),
            "max": cfg.license.max_active,
            "free_remaining": max(0, cfg.license.free_activations - activations),
            "cooldown_until": cooldown_until,
        },
        "specialization_level": cfg.specialization_level,
        "level_cap": cfg.level_cap,
        "unlicensed_level_cap": cfg.unlicensed_level_cap,
    }
