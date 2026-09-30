"""Importing this package registers every content type with the content registry."""

from app.services.content.types import (  # noqa: F401
    abilities,
    afk_profiles,
    balance,
    classes,
    items,
    professions,
    race,
    world,
)
