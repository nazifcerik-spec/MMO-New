"""Import all model modules so Base.metadata is complete (used by Alembic and tests)."""

from app.models import (  # noqa: F401
    abilities,
    afk,
    auth,
    character,
    classes,
    content,
    crafting,
    items,
    localization,
    party,
    professions,
    profiles,
    progression,
    race,
    world,
)
