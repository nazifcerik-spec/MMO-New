from fastapi import APIRouter

from app.api import (
    afk,
    afk_profiles,
    auth,
    characters,
    classes,
    content_public,
    crafting,
    economy,
    goals,
    health,
    i18n,
    inventory,
    items,
    overview,
    party,
    professions,
    progression,
    talents,
    world,
)
from app.api.admin import content as admin_content
from app.api.admin import items as admin_items
from app.api.admin import localization as admin_localization
from app.api.admin import users as admin_users

api_router = APIRouter(prefix="/api/v1")
_MODULES = (
    health,
    i18n,
    auth,
    characters,
    content_public,
    progression,
    classes,
    talents,
    afk_profiles,
    world,
    afk,
    items,
    inventory,
    professions,
    crafting,
    economy,
    party,
    goals,
    overview,
    admin_localization,
    admin_users,
    admin_items,
    admin_content,
)
for module in _MODULES:
    api_router.include_router(module.router)

root_router = APIRouter()
root_router.include_router(health.router)
