from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.content.names import name_key, validate_name
from app.core.config import get_settings
from app.core.errors import ConflictError, NotFoundError, ValidationFailedError
from app.models.character import Character, CharacterSettings
from app.services import audit, character_options

# Hooks run in the creation transaction (e.g. class progression row). Registered via services.plugins.
POST_CREATE_HOOKS: list[Any] = []


async def list_characters(db: AsyncSession, user_id: int) -> list[Character]:
    return list(
        (
            await db.execute(
                select(Character)
                .where(Character.user_id == user_id, Character.deleted_at.is_(None))
                .order_by(Character.created_at)
            )
        ).scalars()
    )


async def get_owned(db: AsyncSession, user_id: int, character_id: int, *, for_update: bool = False) -> Character:
    stmt = select(Character).where(
        Character.id == character_id, Character.user_id == user_id, Character.deleted_at.is_(None)
    )
    if for_update:
        stmt = stmt.with_for_update()
    ch = (await db.execute(stmt)).scalar_one_or_none()
    if ch is None:  # same response for "not yours" and "does not exist"
        raise NotFoundError("Character not found")
    return ch


async def get_any(db: AsyncSession, character_id: int, *, for_update: bool = False) -> Character:
    """Staff lookup (callers enforce permissions)."""
    stmt = select(Character).where(Character.id == character_id, Character.deleted_at.is_(None))
    if for_update:
        stmt = stmt.with_for_update()
    ch = (await db.execute(stmt)).scalar_one_or_none()
    if ch is None:
        raise NotFoundError("Character not found")
    return ch


async def is_name_available(db: AsyncSession, name: str) -> bool:
    key = name_key(name)
    hit = (
        await db.execute(select(Character.id).where(Character.name_normalized == key, Character.deleted_at.is_(None)))
    ).first()
    return hit is None


async def create_character(db: AsyncSession, *, user_id: int, name: str, race_id: int, base_class_id: int) -> Character:
    display = validate_name(name)
    count = (
        await db.execute(
            select(func.count())
            .select_from(Character)
            .where(Character.user_id == user_id, Character.deleted_at.is_(None))
        )
    ).scalar_one()
    if count >= get_settings().max_characters_per_account:
        raise ValidationFailedError("Character limit reached", code="character_limit")
    await character_options.validate_choice(db, race_id, base_class_id)
    ch = Character(
        user_id=user_id,
        name=display,
        name_normalized=name_key(display),
        race_id=race_id,
        base_class_id=base_class_id,
        level=1,
        xp=0,
        unspent_stat_points=0,
    )
    db.add(ch)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise ConflictError("Name is already taken", code="name_taken") from exc
    db.add(CharacterSettings(character_id=ch.id))
    for hook in POST_CREATE_HOOKS:
        await hook(db, ch)
    await audit.record(
        db,
        actor_id=user_id,
        action="character.create",
        entity_type="character",
        entity_id=ch.id,
        after={"name": display, "race_id": race_id, "base_class_id": base_class_id},
    )
    return ch


async def soft_delete_character(db: AsyncSession, *, user_id: int, character_id: int) -> None:
    ch = await get_owned(db, user_id, character_id, for_update=True)
    ch.deleted_at = datetime.now(UTC)
    await audit.record(
        db,
        actor_id=user_id,
        action="character.delete",
        entity_type="character",
        entity_id=ch.id,
        before={"name": ch.name},
    )
