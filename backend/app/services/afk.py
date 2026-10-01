"""AFK sessions: immutable start snapshot, deterministic resolve, exactly-once claim, sweeper and replay."""

import asyncio
import secrets
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError, ValidationFailedError
from app.db.redis import get_redis
from app.game_engine import afk as engine
from app.game_engine import progression as prog
from app.game_engine.loot import LootConfig, pity_visible
from app.models.afk import AfkDailyUsage, AfkSession, CharacterAfkStats
from app.models.character import Character
from app.services import afk_profiles, audit, classes, combat_snapshot, progression, wallet, world
from app.services.content import service as content_service
from app.services.content.types.afk_profiles import RISK_LEVELS, RiskProfiles
from app.services.content.types.balance import get_published_balance

# Extension points for systems added later. All are async and must be idempotent on the given key.
LOOT_GRANTERS: list[Any] = []  # (db, character, drops, key) -> list of granted drop dicts (Phase 16/19)
POTION_CONSUMERS: list[Any] = []  # (db, character, qty, key) -> None (Phase 16)
DURABILITY_HANDLERS: list[Any] = []  # (db, character, loss_pct, key) -> None (Phase 16)
PROFESSION_TASK_VALIDATORS: list[Any] = []  # (db, character, task) -> dict normalized task (Phase 17)
PROFESSION_TASK_RESOLVERS: list[Any] = []  # (db, character, snapshot, result, key) -> dict (Phase 17)
RESTED_PROVIDERS: list[Any] = []  # (db, character, cfg) -> bonus percent; only used when rested is enabled
CLAIM_LOCK_TTL_MS = 30_000
MAX_HISTORY = 50


def now_utc() -> datetime:
    return datetime.now(UTC)


async def _cfg(db: AsyncSession) -> engine.AfkBalance:
    return await get_published_balance(db, "afk", engine.AfkBalance)


async def active_session(db: AsyncSession, character_id: int, *, for_update: bool = False) -> AfkSession | None:
    stmt = select(AfkSession).where(
        AfkSession.character_id == character_id, AfkSession.status.in_(("running", "resolved"))
    )
    if for_update:
        stmt = stmt.with_for_update()
    return (await db.execute(stmt)).scalar_one_or_none()


async def _reserve_days(
    db: AsyncSession, user_id: int, cfg: engine.AfkBalance, start: datetime, seconds: int
) -> dict[date, float]:
    """Lock the account's player-day usage rows touched by this session and reserve the planned seconds.
    Returns prior usage per day (used to slice efficiency bands deterministically at start)."""
    slices = engine.day_slices(cfg, start, seconds)
    days = sorted(d for d, _ in slices)
    await db.execute(
        insert(AfkDailyUsage)
        .values([{"user_id": user_id, "day": d, "seconds": 0} for d in days])
        .on_conflict_do_nothing(index_elements=["user_id", "day"])
    )
    rows = {
        r.day: r
        for r in (
            await db.execute(
                select(AfkDailyUsage)
                .where(AfkDailyUsage.user_id == user_id, AfkDailyUsage.day.in_(days))
                .order_by(AfkDailyUsage.day)
                .with_for_update()
            )
        ).scalars()
    }
    prior = {d: float(rows[d].seconds) for d in days}
    for d, secs in slices:
        rows[d].seconds += round(secs)
    return prior


async def _true_up_days(db: AsyncSession, session: AfkSession, used: dict[date, float]) -> None:
    snap = session.snapshot
    planned: dict[str, float] = {}
    for s in snap["segments"]:
        planned[s["day"]] = planned.get(s["day"], 0.0) + s["end_s"] - s["start_s"]
    for day_str, secs in planned.items():
        d = date.fromisoformat(day_str)
        refund = round(secs) - round(used.get(d, 0.0))
        if refund <= 0:
            continue
        row = (
            await db.execute(
                select(AfkDailyUsage)
                .where(AfkDailyUsage.user_id == session.user_id, AfkDailyUsage.day == d)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if row is not None:
            row.seconds = max(0, row.seconds - refund)


async def _stats(db: AsyncSession, character_id: int, *, for_update: bool = False) -> CharacterAfkStats:
    await db.execute(
        insert(CharacterAfkStats)
        .values(character_id=character_id)
        .on_conflict_do_nothing(index_elements=["character_id"])
    )
    stmt = select(CharacterAfkStats).where(CharacterAfkStats.character_id == character_id)
    if for_update:
        stmt = stmt.with_for_update()
    return (await db.execute(stmt)).scalar_one()


async def _build_summary(db: AsyncSession, character: Character) -> dict[str, Any]:
    row = await classes.get_progression_row(db, character)
    profile = await afk_profiles.get_profile(db, character)
    return {
        "level": character.level,
        "class": row.base_class_code,
        "branch": row.branch_code,
        "specialization": row.specialization_code,
        "talent_points": row.talent_points_spent,
        "mode": profile.mode,
        "stance": profile.stance,
        "passive_profile": profile.passive_profile_code,
        "target_priority": profile.target_priority,
        "potion_threshold_pct": profile.potion_threshold_pct,
    }


async def start(
    db: AsyncSession,
    *,
    character: Character,
    zone_code: str,
    duration_s: int,
    risk_level: str | None,
    idempotency_key: str,
    profession_task: dict[str, Any] | None = None,
    now: datetime | None = None,
    group: dict[str, Any] | None = None,
) -> AfkSession:
    """Caller holds a row lock on the character. Snapshot everything the result depends on.

    `group` (party AFK): {player, party, group_id, seed, loot_salt, power_pct} — this member's pre-built snapshot,
    the frozen ally snapshots, the shared fight seed and a personal loot salt."""
    replay = (
        await db.execute(
            select(AfkSession).where(
                AfkSession.character_id == character.id, AfkSession.start_idempotency_key == idempotency_key
            )
        )
    ).scalar_one_or_none()
    if replay is not None:
        return replay
    if await active_session(db, character.id) is not None:
        raise ConflictError("An AFK session is already active", code="afk_session_active")
    cfg = await _cfg(db)
    if not cfg.min_session_seconds <= duration_s <= cfg.max_session_seconds:
        raise ValidationFailedError(
            f"Duration must be {cfg.min_session_seconds}-{cfg.max_session_seconds} s", code="afk_invalid_duration"
        )
    zone_row = await world.get_zone(db, zone_code)
    unmet = await world.unmet_requirements(db, character, zone_row)
    if unmet:
        raise ConflictError("Zone requirements not met", code="zone_locked", details=unmet)
    bundle = await world.load_bundle(db, zone_code)
    profile = await afk_profiles.get_profile(db, character)
    risk_code = risk_level or profile.risk_level
    if risk_code not in RISK_LEVELS:
        raise ValidationFailedError("Unknown risk level", code="invalid_risk")
    risks = await get_published_balance(db, "risk_profiles", RiskProfiles)
    task = None
    if profession_task is not None:
        if not PROFESSION_TASK_VALIDATORS:
            raise ValidationFailedError("Profession tasks are not available yet", code="profession_task_unavailable")
        for check in PROFESSION_TASK_VALIDATORS:
            task = await check(db, character, {**profession_task, "zone_code": zone_code})
    started = now or now_utc()
    rules, extra = await afk_profiles.resolved_rules(db, profile, encounter_type="normal")
    boss_rules, _ = await afk_profiles.resolved_rules(db, profile, encounter_type="boss")
    if group is not None:
        player = group["player"]
    else:
        player = afk_profiles.with_extra_effects(await combat_snapshot.character_snapshot(db, character), extra)
    potions = await afk_profiles.potion_count(db, character)
    prog_cfg = await progression.load_config(db)
    xp_per_unit = prog.reference_xp_per_hour(prog_cfg, character.level) * cfg.reference_cycle_s / 3600
    xp_per_unit /= cfg.reference_units_per_fight
    rested = 0.0
    if cfg.rested.enabled:
        for p in RESTED_PROVIDERS:
            rested += float(await p(db, character, cfg))
        rested = min(rested, cfg.rested.max_bonus_pct)
    prior = await _reserve_days(db, character.user_id, cfg, started, duration_s)
    stats = await _stats(db, character.id)
    snap = engine.AfkSnapshot(
        character_id=character.id,
        character_level=character.level,
        character_xp=character.xp,
        player=player,
        strategy=afk_profiles.strategy_for(profile, potions),
        rules=tuple(r.model_dump(exclude_none=True) for r in rules.rules),
        boss_rules=tuple(r.model_dump(exclude_none=True) for r in boss_rules.rules),
        zone=bundle,
        risk=engine.RiskSnapshot(code=risk_code, **risks.profiles[risk_code].model_dump()),
        combat=await combat_snapshot.load_combat_config(db),
        afk=cfg,
        xp_per_unit=round(xp_per_unit, 6),
        over_level_pct=engine.over_level_pct(cfg, character.level, bundle.max_level),
        rested_bonus_pct=rested,
        potions_reserved=potions,
        pity_start=stats.pity_counter,
        loot=await get_published_balance(db, "loot", LootConfig),
        profession_task=task,
        party=tuple(group["party"]) if group else (),
        group_id=group["group_id"] if group else None,
        loot_salt=group["loot_salt"] if group else 0,
        party_power_pct_per_member=group["power_pct"] if group else 0.0,
        segments=engine.efficiency_segments(cfg, started, duration_s, prior),
        planned_seconds=duration_s,
        content_version=await content_service.current_release_version(db),
        build=await _build_summary(db, character),
    )
    session = AfkSession(
        character_id=character.id,
        user_id=character.user_id,
        status="running",
        zone_code=zone_code,
        risk_level=risk_code,
        started_at=started,
        ends_at=started + timedelta(seconds=duration_s),
        seed=group["seed"] if group else secrets.randbits(62),
        start_idempotency_key=idempotency_key,
        group_id=group["group_id"] if group else None,
        snapshot=snap.model_dump(mode="json"),
        snapshot_hash=engine.snapshot_hash(snap),
        content_version=snap.content_version,
    )
    db.add(session)
    await db.flush()
    await audit.record(
        db,
        actor_id=character.user_id,
        action="afk.start",
        entity_type="afk_session",
        entity_id=session.id,
        meta={"zone": zone_code, "risk": risk_code, "duration_s": duration_s, "character_id": character.id},
    )
    return session


def elapsed_s(session: AfkSession, now: datetime) -> float:
    end = min(now, session.stopped_at or session.ends_at, session.ends_at)
    return max(0.0, (end - session.started_at).total_seconds())


def is_finished(session: AfkSession, now: datetime) -> bool:
    return session.stopped_at is not None or now >= session.ends_at


async def stop(db: AsyncSession, *, character: Character, now: datetime | None = None) -> AfkSession:
    session = await active_session(db, character.id, for_update=True)
    if session is None:
        raise NotFoundError("No active AFK session", code="afk_no_session")
    now = now or now_utc()
    if session.status == "running" and session.stopped_at is None and now < session.ends_at:
        session.stopped_at = now
        await audit.record(
            db, actor_id=character.user_id, action="afk.stop", entity_type="afk_session", entity_id=session.id
        )
    return session


def _resolve_sync(snapshot: dict[str, Any], seed: int, elapsed: float) -> dict[str, Any]:
    return engine.resolve(engine.AfkSnapshot.model_validate(snapshot), seed, elapsed)


async def resolve(session: AfkSession, now: datetime) -> None:
    """Deterministic, CPU-bound: runs off the event loop. Caller holds the row lock."""
    if session.status != "running":
        return
    result = await asyncio.to_thread(_resolve_sync, session.snapshot, session.seed, elapsed_s(session, now))
    session.result = result
    session.result_hash = result["hash"]
    session.resolved_at = now
    session.status = "resolved"


def signals(
    result: dict[str, Any],
    before: dict[str, Any],
    after: dict[str, Any],
    cfg: engine.AfkBalance,
    loot: LootConfig | None = None,
) -> list[dict[str, Any]]:
    """3-Hour Satisfaction Rule: every finished session reports at least one visible progress signal."""
    out: list[dict[str, Any]] = []
    if after["levels_gained"]:
        out.append({"kind": "level_up", "levels": after["levels_gained"], "level": after["level_after"]})
    if result["xp"] and before["xp_to_next"]:
        out.append({"kind": "xp_progress", "percent": round(100 * result["xp"] / before["xp_to_next"], 1)})
    if result["boss_kills"]:
        out.append({"kind": "boss_kills", "count": result["boss_kills"]})
    rare = [d for d in result["drops"] if d.get("rarity") in ("rare", "epic", "legendary", "mythic", "relic")]
    if rare:
        out.append({"kind": "rare_drops", "count": sum(d["qty"] for d in rare)})
    if result["gold"] > 0:
        out.append({"kind": "gold", "amount": result["gold"]})
    if loot is None:
        out.append({"kind": "pity_progress", "percent": round(100 * result["pity_end"] / cfg.pity_threshold_fights, 1)})
    elif pity_visible(loot, "afk"):
        out.append(
            {"kind": "pity_progress", "percent": round(100 * result["pity_end"] / loot.pity.threshold_fights, 1)}
        )
    return out


async def _lock(key: str) -> str | None:
    token = secrets.token_hex(8)
    ok = await get_redis().set(key, token, nx=True, px=CLAIM_LOCK_TTL_MS)
    return token if ok else None


async def _unlock(key: str, token: str) -> None:
    redis = get_redis()
    if await redis.get(key) == token:
        await redis.delete(key)


async def claim(
    db: AsyncSession, *, character: Character, idempotency_key: str, now: datetime | None = None
) -> dict[str, Any]:
    """Exactly-once reward grant. Guarded by a Redis lock (fast fail for concurrent clicks), a DB row lock on
    the session, the unique claim key, and idempotent XP/gold ledgers keyed by session id."""
    replay = (
        await db.execute(
            select(AfkSession).where(
                AfkSession.character_id == character.id, AfkSession.claim_idempotency_key == idempotency_key
            )
        )
    ).scalar_one_or_none()
    if replay is not None and replay.claim_result is not None:
        return {**replay.claim_result, "replayed": True}
    lock_key = f"afk:claim:{character.id}"
    token = await _lock(lock_key)
    if token is None:
        raise ConflictError("Claim already in progress", code="afk_claim_in_progress")
    try:
        return await _claim_locked(db, character=character, idempotency_key=idempotency_key, now=now or now_utc())
    finally:
        await _unlock(lock_key, token)


async def _claim_locked(
    db: AsyncSession, *, character: Character, idempotency_key: str, now: datetime
) -> dict[str, Any]:
    session = await active_session(db, character.id, for_update=True)
    if session is None:
        raise NotFoundError("No AFK session to claim", code="afk_no_session")
    if not is_finished(session, now):
        raise ConflictError(
            "AFK session still running", code="afk_not_finished", details={"ends_at": session.ends_at.isoformat()}
        )
    await resolve(session, now)
    assert session.result is not None
    result = session.result
    cfg = engine.AfkBalance.model_validate(session.snapshot["afk"])
    key = f"afk:{session.id}"
    prog_cfg = await progression.load_config(db)
    before = {"level": character.level, "xp": character.xp, "xp_to_next": prog.xp_to_next(prog_cfg, character.level)}
    xp = await progression.grant_xp(
        db,
        character=character,
        amount=int(result["xp"]),
        idempotency_key=key,
        source_type="afk",
        source_id=str(session.id),
    )
    if result["gold"] > 0:
        await wallet.change_gold(
            db,
            character_id=character.id,
            delta=int(result["gold"]),
            reason="afk_reward",
            idempotency_key=f"{key}:gold",
            ref_type="afk_session",
            ref_id=str(session.id),
        )
    granted: list[dict[str, Any]] = []
    for grant in LOOT_GRANTERS:
        granted += await grant(db, character, result["drops"], f"{key}:loot")
    if result["potions_used"]:
        for consume in POTION_CONSUMERS:
            await consume(db, character, result["potions_used"], f"{key}:potions")
    if result["durability_loss_pct"]:
        for handler in DURABILITY_HANDLERS:
            await handler(db, character, result["durability_loss_pct"], f"{key}:durability")
    profession: dict[str, Any] | None = None
    if session.snapshot.get("profession_task"):
        for resolver in PROFESSION_TASK_RESOLVERS:
            profession = await resolver(db, character, session.snapshot, result, f"{key}:profession")
    used = engine.used_by_day(
        tuple(engine.Segment.model_validate(s) for s in session.snapshot["segments"]), result["elapsed_s"]
    )
    await _true_up_days(db, session, used)
    stats = await _stats(db, character.id, for_update=True)
    stats.pity_counter = int(result["pity_end"])
    stats.sessions_claimed += 1
    stats.total_seconds += int(result["elapsed_s"])
    stats.last_claimed_at = now
    summary = {
        "session_id": session.id,
        "zone_code": session.zone_code,
        "risk_level": session.risk_level,
        "result": {k: v for k, v in result.items() if k not in ("samples", "hash")},
        "xp": xp,
        "gold": result["gold"],
        "loot_granted": granted,
        "loot_pending": [] if LOOT_GRANTERS else result["drops"],
        "profession": profession,
        "signals": signals(
            result,
            before,
            xp,
            cfg,
            LootConfig.model_validate(session.snapshot["loot"]) if session.snapshot.get("loot") else None,
        ),
    }
    session.status = "claimed"
    session.claimed_at = now
    session.claim_idempotency_key = idempotency_key
    session.claim_result = summary
    await audit.record(
        db,
        actor_id=character.user_id,
        action="afk.claim",
        entity_type="afk_session",
        entity_id=session.id,
        meta={"xp": result["xp"], "gold": result["gold"], "deaths": result["deaths"], "hash": result["hash"]},
    )
    await db.flush()
    return {**summary, "replayed": False}


async def sweep(db: AsyncSession, *, now: datetime | None = None, limit: int = 50) -> int:
    """Pre-resolve finished sessions (background job). Safe to run concurrently (SKIP LOCKED)."""
    now = now or now_utc()
    rows = list(
        (
            await db.execute(
                select(AfkSession)
                .where(AfkSession.status == "running", (AfkSession.ends_at <= now) | AfkSession.stopped_at.is_not(None))
                .order_by(AfkSession.ends_at)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        ).scalars()
    )
    for s in rows:
        await resolve(s, now)
    await db.flush()
    return len(rows)


async def replay(db: AsyncSession, session_id: int) -> dict[str, Any]:
    """Re-run resolution from the stored snapshot + seed and compare with the stored result hash."""
    session = await db.get(AfkSession, session_id)
    if session is None:
        raise NotFoundError("AFK session not found", code="afk_no_session")
    if session.result is None:
        raise ConflictError("Session not resolved yet", code="afk_not_resolved")
    again = await asyncio.to_thread(_resolve_sync, session.snapshot, session.seed, float(session.result["elapsed_s"]))
    return {
        "session_id": session.id,
        "stored_hash": session.result_hash,
        "replay_hash": again["hash"],
        "match": again["hash"] == session.result_hash,
        "snapshot_hash_ok": engine.snapshot_hash(engine.AfkSnapshot.model_validate(session.snapshot))
        == session.snapshot_hash,
    }


def session_view(session: AfkSession, now: datetime, locale_names: dict[str, str] | None = None) -> dict[str, Any]:
    snap = session.snapshot
    return {
        "id": session.id,
        "status": session.status,
        "zone_code": session.zone_code,
        "zone_name": (locale_names or {}).get(session.zone_code, session.zone_code),
        "risk_level": session.risk_level,
        "started_at": session.started_at.isoformat(),
        "ends_at": session.ends_at.isoformat(),
        "stopped_at": session.stopped_at.isoformat() if session.stopped_at else None,
        "server_now": now.isoformat(),
        "remaining_s": 0 if is_finished(session, now) else round((session.ends_at - now).total_seconds()),
        "elapsed_s": round(elapsed_s(session, now)),
        "claimable": is_finished(session, now) and session.status in ("running", "resolved"),
        "build": snap.get("build", {}),
        "player_stats": {k: snap["player"]["stats"].get(k) for k in ("max_hp", "attack_power", "spell_power", "armor")},
        "efficiency": [{"from_s": s["start_s"], "to_s": s["end_s"], "percent": s["percent"]} for s in snap["segments"]],
        "content_version": session.content_version,
        "claim": session.claim_result,
    }


async def history(db: AsyncSession, character_id: int, *, before_id: int | None, limit: int) -> list[AfkSession]:
    stmt = select(AfkSession).where(AfkSession.character_id == character_id, AfkSession.status == "claimed")
    if before_id is not None:
        stmt = stmt.where(AfkSession.id < before_id)
    return list((await db.execute(stmt.order_by(AfkSession.id.desc()).limit(min(limit, MAX_HISTORY)))).scalars())
