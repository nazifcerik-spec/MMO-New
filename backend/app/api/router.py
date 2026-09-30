from fastapi import APIRouter

from app.api import health

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health.router)

root_router = APIRouter()
root_router.include_router(health.router)
