from fastapi import APIRouter

from app.api import auth, characters, health, i18n
from app.api.admin import localization as admin_localization
from app.api.admin import users as admin_users

api_router = APIRouter(prefix="/api/v1")
for module in (health, i18n, auth, characters, admin_localization, admin_users):
    api_router.include_router(module.router)

root_router = APIRouter()
root_router.include_router(health.router)
