"""Version-1 API router: mounts each route module under `/api/v1`."""

from fastapi import APIRouter

from app.api.v1.health import router as health_router

__all__ = ["v1_router"]

v1_router = APIRouter()
v1_router.include_router(health_router)
