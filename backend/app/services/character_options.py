"""Character-creation choices come from published content (races, base classes); never hardcoded."""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ValidationFailedError
from app.services import races

# Base classes are registered by the class module (Phase 07).
CLASS_OPTION_PROVIDERS: list[Any] = []


async def get_character_options(db: AsyncSession, locale: str) -> dict[str, list[dict[str, Any]]]:
    classes: list[dict[str, Any]] = []
    for provider in CLASS_OPTION_PROVIDERS:
        classes.extend(await provider(db, locale))
    return {"races": await races.race_cards(db, locale), "base_classes": classes}


async def validate_choice(db: AsyncSession, race_id: int, base_class_id: int) -> None:
    options = await get_character_options(db, "en")
    race_ids = {r["id"] for r in options["races"]}
    class_ids = {c["id"] for c in options["base_classes"]}
    if not race_ids or not class_ids:
        raise ValidationFailedError("Race/class content is not available yet", code="content_unavailable")
    if race_id not in race_ids:
        raise ValidationFailedError("Unknown or unavailable race", code="invalid_race")
    if base_class_id not in class_ids:
        raise ValidationFailedError("Unknown or unavailable base class", code="invalid_class")
