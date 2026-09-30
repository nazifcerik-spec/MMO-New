from fastapi import APIRouter

from app.api import health, i18n

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health.router)
api_router.include_router(i18n.router)

root_router = APIRouter()
root_router.include_router(health.router)
