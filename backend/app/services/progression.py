"""Character progression service: XP grants (atomic, idempotent), allocation, templates, respec, stat sheet."""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.content.loader import load_yaml
from app.core.context import get_correlation_id
from app.core.errors import ConflictError, NotFoundError, ValidationFailedError
from app.game_engine import progression as prog
from app.game_engine.stat_calculator import Contribution, StatSheet, allocation_contribution, compute_stat_sheet
from app.game_engine.stats import PRIMARY_STATS
from app.models.character import Character
from app.models.progression import CharacterStatAllocation, ProgressionEvent
from app.services import wallet
from app.services.content.types.balance import get_published_balance

# Hooks filled by later phases (race/class/equipment/talent providers). Each returns stat contributions.
ContributionProvider = Any
CONTRIBUTION_PROVIDERS: list[ContributionProvider] = []
# Provider of class stat tokens {main, secondary, utility, main_damage} for templates (Phase 07).
STAT_TOKEN_PROVIDERS: list[Any] = []
# Provider of respec discount (percent, limit_points) from race effects (Phase 06).
RESPEC_DISCOUNT_PROVIDERS: list[Any] = []


async def load_config(db: AsyncSession) -> prog.ProgressionConfig:
    return await get_published_balance(db, "progression", prog.ProgressionConfig)


async def get_allocation(db: AsyncSession, character_id: int, *, for_update: bool = False) -> CharacterStatAllocation:
    await db.execute(insert(CharacterStatAllocation).values(character_id=character_id).on_conflict_do_nothing())
    stmt = select(CharacterStatAllocation).where(CharacterStatAllocation.character_id == character_id)
    if for_update:
        stmt = stmt.with_for_update()
    return (await db.execute(stmt)).scalar_one()


async def _existing_event(db: AsyncSession, character_id: int, key: str) -> ProgressionEvent | None:
    return (
        await db.execute(
            select(ProgressionEvent).where(
                ProgressionEvent.character_id == character_id, ProgressionEvent.idempotency_key == key
            )
        )
    ).scalar_one_or_none()


async def grant_xp(
    db: AsyncSession,
    *,
    character: Character,
    amount: int,
    idempotency_key: str,
    source_type: str,
    source_id: str | None = None,
    cfg: prog.ProgressionConfig | None = None,
) -> dict[str, Any]:
    """Atomically add XP, process multi-level gains and stat points. Same key => same result, no double grant.
    Caller must hold a row lock on `character` (SELECT ... FOR UPDATE) and commit."""
    if amount < 0:
        raise ValidationFailedError("XP amount must be non-negative", code="invalid_amount")
    prior = await _existing_event(db, character.id, idempotency_key)
    if prior is not None:
        return {**prior.result, "replayed": True}
    cfg = cfg or await load_config(db)
    before = character.level
    res = prog.apply_xp(cfg, character.level, character.xp, amount)
    character.level, character.xp = res.level, res.xp
    character.unspent_stat_points += res.stat_points_gained
    character.mastery_xp += res.overflow_xp
    if res.levels_gained:
        character.last_level_up_at = datetime.now(UTC)
    result = {
        "xp_gained": amount,
        "level_before": before,
        "level_after": res.level,
        "xp": res.xp,
        "levels_gained": res.levels_gained,
        "stat_points_gained": res.stat_points_gained,
        "overflow_xp": res.overflow_xp,
        "breakpoints_crossed": list(res.breakpoints_crossed),
    }
    db.add(
        ProgressionEvent(
            character_id=character.id,
            kind="xp_grant",
            idempotency_key=idempotency_key,
            source_type=source_type,
            source_id=source_id,
            amount=amount,
            level_before=before,
            level_after=res.level,
            result=result,
            correlation_id=get_correlation_id(),
        )
    )
    await db.flush()
    return {**result, "replayed": False}


def _validate_alloc(raw: dict[str, int]) -> dict[str, int]:
    clean: dict[str, int] = {}
    for stat, n in raw.items():
        if stat not in PRIMARY_STATS:
            raise ValidationFailedError(f"Unknown stat {stat}", code="invalid_stat")
        if not isinstance(n, int) or isinstance(n, bool) or n < 0 or n > 3000:
            raise ValidationFailedError("Point amounts must be integers 0..3000", code="invalid_amount")
        if n:
            clean[stat] = n
    if not clean:
        raise ValidationFailedError("Nothing to allocate", code="empty_allocation")
    return clean


async def allocate(
    db: AsyncSession,
    *,
    character: Character,
    points: dict[str, int],
    expected_version: int,
    idempotency_key: str,
    mode: str = "manual",
) -> dict[str, int]:
    prior = await _existing_event(db, character.id, idempotency_key)
    if prior is not None:
        return dict(prior.result["allocation"])
    if character.version != expected_version:
        raise ConflictError(
            "Character changed; reload and retry",
            code="version_conflict",
            details={"current_version": character.version},
        )
    clean = _validate_alloc(points)
    total = sum(clean.values())
    if total > character.unspent_stat_points:
        raise ValidationFailedError(
            "Not enough unspent stat points",
            code="insufficient_points",
            details={"unspent": character.unspent_stat_points, "requested": total},
        )
    alloc = await get_allocation(db, character.id, for_update=True)
    current = alloc.as_dict()
    for s, n in clean.items():
        current[s] += n
    alloc.set_from(current)
    character.unspent_stat_points -= total
    db.add(
        ProgressionEvent(
            character_id=character.id,
            kind=f"allocate_{mode}",
            idempotency_key=idempotency_key,
            amount=total,
            level_before=character.level,
            level_after=character.level,
            result={"added": clean, "allocation": current},
            correlation_id=get_correlation_id(),
        )
    )
    await db.flush()
    return current


def stat_profiles() -> dict[str, dict[str, Any]]:
    return dict(load_yaml("system/stat_profiles.yaml")["profiles"])


async def stat_tokens(db: AsyncSession, character: Character) -> dict[str, str]:
    for provider in STAT_TOKEN_PROVIDERS:
        tokens = await provider(db, character)
        if tokens:
            return dict(tokens)
    return {}


async def template_points(db: AsyncSession, character: Character, profile_code: str, points: int) -> dict[str, int]:
    profile = stat_profiles().get(profile_code)
    if profile is None:
        raise NotFoundError(f"Unknown stat profile {profile_code}")
    try:
        weights = prog.resolve_profile_weights(profile["weights"], await stat_tokens(db, character))
    except ValueError as exc:
        raise ValidationFailedError(str(exc), code="profile_unresolved") from exc
    return prog.distribute_points(points, weights)


async def respec_quote(db: AsyncSession, character: Character) -> dict[str, Any]:
    cfg = await load_config(db)
    alloc = await get_allocation(db, character.id)
    points = sum(alloc.as_dict().values())
    discount, limit = 0.0, None
    for provider in RESPEC_DISCOUNT_PROVIDERS:
        d = await provider(db, character)
        if d:
            discount, limit = d
    cost = prog.respec_cost(cfg, character.level, points, discount_percent=discount, discount_limit_points=limit)
    return {
        "points_refunded": points,
        "gold_cost": cost,
        "discount_percent": discount,
        "discount_limit_points": limit,
        "cooldown_seconds": cfg.respec.cooldown_seconds,
    }


async def respec(db: AsyncSession, *, character: Character, idempotency_key: str) -> dict[str, Any]:
    prior = await _existing_event(db, character.id, idempotency_key)
    if prior is not None:
        return {**prior.result, "replayed": True}
    quote = await respec_quote(db, character)
    if quote["points_refunded"] == 0:
        raise ValidationFailedError("Nothing to reset", code="nothing_to_respec")
    alloc = await get_allocation(db, character.id, for_update=True)
    cfg = await load_config(db)
    if alloc.last_respec_at and cfg.respec.cooldown_seconds:
        elapsed = (datetime.now(UTC) - alloc.last_respec_at).total_seconds()
        if elapsed < cfg.respec.cooldown_seconds:
            raise ConflictError("Respec on cooldown", code="respec_cooldown")
    if quote["gold_cost"]:
        await wallet.change_gold(
            db,
            character_id=character.id,
            delta=-quote["gold_cost"],
            reason="respec",
            idempotency_key=f"respec:{idempotency_key}",
            ref_type="character",
            ref_id=str(character.id),
        )
    alloc.set_from({})
    alloc.last_respec_at = datetime.now(UTC)
    character.unspent_stat_points += quote["points_refunded"]
    result = {**quote, "unspent_after": character.unspent_stat_points}
    db.add(
        ProgressionEvent(
            character_id=character.id,
            kind="respec",
            idempotency_key=idempotency_key,
            amount=quote["points_refunded"],
            level_before=character.level,
            level_after=character.level,
            result=result,
            correlation_id=get_correlation_id(),
        )
    )
    await db.flush()
    return {**result, "replayed": False}


async def contributions(db: AsyncSession, character: Character) -> list[Contribution]:
    alloc = await get_allocation(db, character.id)
    out = [allocation_contribution(alloc.as_dict())]
    for provider in CONTRIBUTION_PROVIDERS:
        out.extend(await provider(db, character))
    return out


async def stat_sheet(db: AsyncSession, character: Character, cfg: prog.ProgressionConfig | None = None) -> StatSheet:
    cfg = cfg or await load_config(db)
    return compute_stat_sheet(cfg, character.level, await contributions(db, character))


async def progression_view(db: AsyncSession, character: Character) -> dict[str, Any]:
    cfg = await load_config(db)
    need = prog.xp_to_next(cfg, character.level)
    nt = prog.next_title(cfg, character.level)
    alloc = await get_allocation(db, character.id)
    return {
        "character_id": character.id,
        "level": character.level,
        "level_cap": cfg.level_cap,
        "xp": character.xp,
        "xp_to_next": need,
        "progress_percent": round(100 * character.xp / need, 2) if need else 100.0,
        "unspent_stat_points": character.unspent_stat_points,
        "mastery_xp": character.mastery_xp,
        "title_code": prog.title_for_level(cfg, character.level),
        "next_title": {"code": nt.code, "level": nt.level} if nt else None,
        "next_breakpoint": prog.next_breakpoint(cfg, character.level),
        "breakpoints": cfg.breakpoints,
        "allocation": alloc.as_dict(),
        "version": character.version,
        "stats": (await stat_sheet(db, character, cfg)).as_dict(),
    }
