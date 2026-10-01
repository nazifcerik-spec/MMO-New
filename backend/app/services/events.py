"""In-process gameplay event bus for long-term goals (quests, achievements). Services emit ONE aggregated event
per meaningful action (an AFK claim, a craft claim, a trade) — never per combat event — and listeners update
counters/progress in the same transaction."""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.character import Character

LISTENERS: list[Any] = []  # async (db, character, event, data) -> None


async def emit(db: AsyncSession, character: Character, event: str, data: dict[str, Any] | None = None) -> None:
    for listener in LISTENERS:
        await listener(db, character, event, data or {})
