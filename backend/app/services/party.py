"""Parties (default size 5): invites, roles, leader actions, online/AFK state, minimal chat and group AFK.

Group AFK: the leader picks zone/duration/risk; every member gets their OWN AfkSession whose snapshot freezes
their stats plus the allies' snapshots at start (Solo Accord is off in parties). Fights share one seed, loot is
personal (salted per member). Joining/leaving later never changes running sessions."""

import secrets
import unicodedata
import uuid
import zlib
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.content.names import name_key
from app.core.errors import ConflictError, NotFoundError, PermissionDeniedError, ValidationFailedError
from app.game_engine import party as rules
from app.models.afk import AfkSession
from app.models.auth import AuthSession
from app.models.character import Character
from app.models.classes import BaseClass
from app.models.party import Party, PartyInvite, PartyMember, PartyMessage
from app.services import afk, afk_profiles, audit, combat_snapshot
from app.services.content.types.balance import get_published_balance


def now_utc() -> datetime:
    return datetime.now(UTC)


async def config(db: AsyncSession) -> rules.PartyConfig:
    return await get_published_balance(db, "party", rules.PartyConfig)


async def _class_code(db: AsyncSession, character: Character) -> str:
    return str((await db.execute(select(BaseClass.code).where(BaseClass.id == character.base_class_id))).scalar_one())


async def _check_role(db: AsyncSession, cfg: rules.PartyConfig, character: Character, role: str | None) -> str:
    code = await _class_code(db, character)
    options = cfg.role_options.get(code, ("dps",))
    if role is None:
        return options[0]
    if role not in options:
        raise ValidationFailedError(f"{code} can take roles {list(options)}", code="invalid_party_role")
    return role


async def membership(db: AsyncSession, character_id: int, *, for_update: bool = False) -> PartyMember | None:
    stmt = select(PartyMember).where(PartyMember.character_id == character_id)
    if for_update:
        stmt = stmt.with_for_update()
    return (await db.execute(stmt)).scalar_one_or_none()


async def _party(db: AsyncSession, party_id: int, *, for_update: bool = True) -> Party:
    stmt = select(Party).where(Party.id == party_id, Party.disbanded_at.is_(None))
    if for_update:
        stmt = stmt.with_for_update()
    p = (await db.execute(stmt)).scalar_one_or_none()
    if p is None:
        raise NotFoundError("Party not found", code="party_not_found")
    return p


async def _members(db: AsyncSession, party_id: int) -> list[PartyMember]:
    return list(
        (
            await db.execute(
                select(PartyMember)
                .where(PartyMember.party_id == party_id)
                .order_by(PartyMember.joined_at, PartyMember.character_id)
            )
        ).scalars()
    )


async def _my_party(db: AsyncSession, character: Character) -> tuple[Party, PartyMember]:
    m = await membership(db, character.id)
    if m is None:
        raise NotFoundError("You are not in a party", code="not_in_party")
    return await _party(db, m.party_id), m


def _require_leader(p: Party, character: Character) -> None:
    if p.leader_character_id != character.id:
        raise PermissionDeniedError("Only the party leader can do that")


# --------------------------------------------------------------------------- lifecycle
async def create(db: AsyncSession, *, character: Character, role: str | None) -> dict[str, Any]:
    if await membership(db, character.id) is not None:
        raise ConflictError("Already in a party", code="already_in_party")
    cfg = await config(db)
    role = await _check_role(db, cfg, character, role)
    p = Party(leader_character_id=character.id, max_size=cfg.max_size)
    db.add(p)
    await db.flush()
    db.add(PartyMember(character_id=character.id, party_id=p.id, user_id=character.user_id, role=role))
    await db.flush()
    await audit.record(db, actor_id=character.user_id, action="party.create", entity_type="party", entity_id=p.id)
    return {"party_id": p.id}


async def invite(db: AsyncSession, *, leader: Character, target_name: str) -> dict[str, Any]:
    p, _ = await _my_party(db, leader)
    _require_leader(p, leader)
    cfg = await config(db)
    target = (
        await db.execute(
            select(Character).where(Character.name_normalized == name_key(target_name), Character.deleted_at.is_(None))
        )
    ).scalar_one_or_none()
    if target is None:
        raise NotFoundError("Character not found", code="character_not_found")
    if await membership(db, target.id) is not None:
        raise ConflictError("That character is already in a party", code="already_in_party")
    members = await _members(db, p.id)
    if any(m.user_id == target.user_id for m in members):
        raise ConflictError("One character per account in a party", code="same_account")
    if len(members) >= p.max_size:
        raise ConflictError("Party is full", code="party_full")
    now = now_utc()
    pending = (
        await db.execute(
            select(PartyInvite).where(
                PartyInvite.party_id == p.id, PartyInvite.character_id == target.id, PartyInvite.status == "pending"
            )
        )
    ).scalar_one_or_none()
    if pending is not None:
        if pending.expires_at > now:
            return {"invite_id": pending.id, "replayed": True}
        pending.status = "expired"
        await db.flush()
    inv = PartyInvite(
        party_id=p.id, character_id=target.id, invited_by=leader.id, status="pending",
        expires_at=now + timedelta(minutes=cfg.invite_ttl_minutes),
    )  # fmt: skip
    db.add(inv)
    await db.flush()
    return {"invite_id": inv.id, "replayed": False}


async def _invite_for(db: AsyncSession, character: Character, invite_id: int) -> PartyInvite:
    inv = (
        await db.execute(
            select(PartyInvite)
            .where(PartyInvite.id == invite_id, PartyInvite.character_id == character.id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if inv is None:
        raise NotFoundError("Invite not found", code="invite_not_found")
    if inv.status != "pending":
        raise ConflictError("Invite is no longer pending", code="invite_closed")
    if inv.expires_at <= now_utc():
        inv.status = "expired"
        await db.flush()
        raise ConflictError("Invite expired", code="invite_expired")
    return inv


async def accept(db: AsyncSession, *, character: Character, invite_id: int, role: str | None) -> dict[str, Any]:
    inv = await _invite_for(db, character, invite_id)
    if await membership(db, character.id) is not None:
        raise ConflictError("Already in a party", code="already_in_party")
    cfg = await config(db)
    role = await _check_role(db, cfg, character, role)
    p = await _party(db, inv.party_id)  # row lock serializes concurrent accepts against max_size
    members = await _members(db, p.id)
    if len(members) >= p.max_size:
        raise ConflictError("Party is full", code="party_full")
    if any(m.user_id == character.user_id for m in members):
        raise ConflictError("One character per account in a party", code="same_account")
    db.add(PartyMember(character_id=character.id, party_id=p.id, user_id=character.user_id, role=role))
    inv.status = "accepted"
    await db.flush()
    return {"party_id": p.id, "role": role}


async def decline(db: AsyncSession, *, character: Character, invite_id: int) -> None:
    inv = await _invite_for(db, character, invite_id)
    inv.status = "declined"
    await db.flush()


async def _remove(db: AsyncSession, p: Party, character_id: int) -> None:
    m = await membership(db, character_id, for_update=True)
    if m is None or m.party_id != p.id:
        raise NotFoundError("Not a member of this party", code="not_in_party")
    await db.delete(m)
    await db.flush()
    rest = await _members(db, p.id)
    if not rest:
        p.disbanded_at = now_utc()
    elif p.leader_character_id == character_id:
        p.leader_character_id = rest[0].character_id  # longest-standing member inherits leadership
    await db.flush()


async def leave(db: AsyncSession, *, character: Character) -> None:
    p, _ = await _my_party(db, character)
    await _remove(db, p, character.id)


async def kick(db: AsyncSession, *, leader: Character, target_id: int) -> None:
    p, _ = await _my_party(db, leader)
    _require_leader(p, leader)
    if target_id == leader.id:
        raise ValidationFailedError("Use leave instead", code="invalid_target")
    await _remove(db, p, target_id)
    await audit.record(
        db,
        actor_id=leader.user_id,
        action="party.kick",
        entity_type="party",
        entity_id=p.id,
        meta={"target": target_id},
    )


async def set_leader(db: AsyncSession, *, leader: Character, target_id: int) -> None:
    p, _ = await _my_party(db, leader)
    _require_leader(p, leader)
    m = await membership(db, target_id)
    if m is None or m.party_id != p.id:
        raise NotFoundError("Not a member of this party", code="not_in_party")
    p.leader_character_id = target_id
    await db.flush()


async def set_role(db: AsyncSession, *, character: Character, role: str) -> dict[str, Any]:
    _, m = await _my_party(db, character)
    m.role = await _check_role(db, await config(db), character, role)
    await db.flush()
    return {"role": m.role}


# --------------------------------------------------------------------------- chat (minimal contract)
def clean_message(body: str, max_length: int) -> str:
    text = unicodedata.normalize("NFC", body)
    text = "".join(ch for ch in text if ch in "\n\t" or unicodedata.category(ch)[0] != "C").strip()
    if not text or len(text) > max_length:
        raise ValidationFailedError(f"Message must be 1-{max_length} characters", code="invalid_message")
    return text


async def send_message(db: AsyncSession, *, character: Character, body: str, key: str) -> dict[str, Any]:
    p, _ = await _my_party(db, character)
    prior = (
        await db.execute(
            select(PartyMessage).where(PartyMessage.character_id == character.id, PartyMessage.client_key == key)
        )
    ).scalar_one_or_none()
    if prior is not None:
        return {"id": prior.id, "replayed": True}
    cfg = await config(db)
    msg = PartyMessage(
        party_id=p.id, character_id=character.id, body=clean_message(body, cfg.chat.max_length), client_key=key
    )
    db.add(msg)
    await db.flush()
    return {"id": msg.id, "replayed": False}


async def messages(db: AsyncSession, *, character: Character, after_id: int | None) -> list[dict[str, Any]]:
    p, _ = await _my_party(db, character)
    cfg = await config(db)
    stmt = (
        select(PartyMessage, Character.name)
        .join(Character, Character.id == PartyMessage.character_id)
        .where(PartyMessage.party_id == p.id)
    )
    if after_id is not None:
        stmt = stmt.where(PartyMessage.id > after_id).order_by(PartyMessage.id).limit(cfg.chat.page_size)
        rows = (await db.execute(stmt)).all()
    else:
        rows = list(reversed((await db.execute(stmt.order_by(PartyMessage.id.desc()).limit(cfg.chat.page_size))).all()))
    return [
        {"id": m.id, "character_id": m.character_id, "name": name, "body": m.body, "at": m.created_at.isoformat()}
        for m, name in rows
    ]


# --------------------------------------------------------------------------- view
async def _online_users(db: AsyncSession, user_ids: list[int], window_min: int) -> set[int]:
    since = now_utc() - timedelta(minutes=window_min)
    rows = await db.execute(
        select(AuthSession.user_id)
        .where(AuthSession.user_id.in_(user_ids), AuthSession.last_seen_at >= since, AuthSession.revoked_at.is_(None))
        .group_by(AuthSession.user_id)
    )
    return set(rows.scalars())


def _afk_state(s: AfkSession | None) -> dict[str, Any] | None:
    if s is None:
        return None
    return {"zone_code": s.zone_code, "ends_at": s.ends_at.isoformat(), "group": s.group_id is not None}


async def view(db: AsyncSession, character: Character) -> dict[str, Any]:
    cfg = await config(db)
    now = now_utc()
    invites = (
        await db.execute(
            select(PartyInvite, Character.name)
            .join(Character, Character.id == PartyInvite.invited_by)
            .where(
                PartyInvite.character_id == character.id, PartyInvite.status == "pending", PartyInvite.expires_at > now
            )
        )
    ).all()
    my_invites = [
        {"id": i.id, "party_id": i.party_id, "from": name, "expires_at": i.expires_at.isoformat()}
        for i, name in invites
    ]
    code = await _class_code(db, character)
    base = {"invites": my_invites, "role_options": list(cfg.role_options.get(code, ("dps",))), "max_size": cfg.max_size}
    m = await membership(db, character.id)
    if m is None:
        return {**base, "party": None}
    p = await _party(db, m.party_id, for_update=False)
    members = await _members(db, p.id)
    chars = {
        c.id: c
        for c in (
            await db.execute(select(Character).where(Character.id.in_([x.character_id for x in members])))
        ).scalars()
    }
    classes = dict((await db.execute(select(BaseClass.id, BaseClass.code))).all())
    online = await _online_users(db, [x.user_id for x in members], cfg.online_window_minutes)
    sessions = {
        s.character_id: s
        for s in (
            await db.execute(
                select(AfkSession).where(
                    AfkSession.character_id.in_(list(chars)), AfkSession.status.in_(("running", "resolved"))
                )
            )
        ).scalars()
    }
    pending = (
        await db.execute(
            select(func.count())
            .select_from(PartyInvite)
            .where(PartyInvite.party_id == p.id, PartyInvite.status == "pending", PartyInvite.expires_at > now)
        )
    ).scalar_one()
    roles = [x.role for x in members]
    return {
        **base,
        "party": {
            "id": p.id,
            "leader_character_id": p.leader_character_id,
            "max_size": p.max_size,
            "pending_invites": int(pending),
            "members": [
                {
                    "character_id": x.character_id,
                    "name": chars[x.character_id].name,
                    "level": chars[x.character_id].level,
                    "class_code": classes.get(chars[x.character_id].base_class_id),
                    "role": x.role,
                    "online": x.user_id in online,
                    "afk": _afk_state(sessions.get(x.character_id)),
                    "leader": x.character_id == p.leader_character_id,
                }
                for x in members
            ],
            "composition_bonuses": [b.code for b in rules.active_bonuses(cfg, roles)],
        },
    }


# --------------------------------------------------------------------------- group AFK
async def group_afk_start(
    db: AsyncSession, *, leader: Character, zone_code: str, duration_s: int, risk_level: str | None, key: str
) -> dict[str, Any]:
    p, _ = await _my_party(db, leader)
    _require_leader(p, leader)
    replay = (
        await db.execute(
            select(AfkSession).where(
                AfkSession.character_id == leader.id, AfkSession.start_idempotency_key == f"group:{key}:{leader.id}"
            )
        )
    ).scalar_one_or_none()
    if replay is not None:
        group = list((await db.execute(select(AfkSession).where(AfkSession.group_id == replay.group_id))).scalars())
        return {"group_id": replay.group_id, "sessions": {s.character_id: s.id for s in group}, "replayed": True}
    members = await _members(db, p.id)
    if len(members) < 2:
        raise ConflictError("Group AFK needs at least two members", code="party_too_small")
    cfg = await config(db)
    ids = sorted(m.character_id for m in members)
    chars = {
        c.id: c
        for c in (
            await db.execute(select(Character).where(Character.id.in_(ids)).order_by(Character.id).with_for_update())
        ).scalars()
    }
    roles = [m.role for m in members]
    bonus_effects = [e for b in rules.active_bonuses(cfg, roles) for e in b.effects]
    snaps = {}
    for cid in ids:
        ch = chars[cid]
        if await afk.active_session(db, cid) is not None:
            raise ConflictError(
                f"{ch.name} already has an AFK session", code="afk_session_active", details={"character_id": cid}
            )
        profile = await afk_profiles.get_profile(db, ch)
        _, extra = await afk_profiles.resolved_rules(db, profile, encounter_type="normal")
        role = next(m.role for m in members if m.character_id == cid)
        s = await combat_snapshot.character_snapshot(db, ch, party_size=len(ids))
        s = afk_profiles.with_extra_effects(s, [*extra, *bonus_effects])
        snaps[cid] = s.model_copy(
            update={"role": "healer" if role == "healer" else ("tank" if role == "tank" else s.role)}
        )
    group_id = str(uuid.uuid4())
    seed = secrets.randbits(62)
    risk = risk_level or (await afk_profiles.get_profile(db, leader)).risk_level
    sessions = {}
    for cid in ids:
        session = await afk.start(
            db, character=chars[cid], zone_code=zone_code, duration_s=duration_s, risk_level=risk,
            idempotency_key=f"group:{key}:{cid}",
            group={"player": snaps[cid], "party": [snaps[o] for o in ids if o != cid], "group_id": group_id,
                   "seed": seed, "loot_salt": zlib.crc32(f"{group_id}:{cid}".encode()) or 1,
                   "power_pct": cfg.enemy_power_pct_per_extra_member},
        )  # fmt: skip
        sessions[cid] = session.id
    await audit.record(
        db, actor_id=leader.user_id, action="party.group_afk", entity_type="party", entity_id=p.id,
        meta={"group_id": group_id, "zone": zone_code, "members": ids, "duration_s": duration_s},
    )  # fmt: skip
    return {"group_id": group_id, "sessions": sessions, "replayed": False}
