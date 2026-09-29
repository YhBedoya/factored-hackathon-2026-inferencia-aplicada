"""Version-1 API router: mounts each route module under `/api/v1`."""

from fastapi import APIRouter

from app.api.v1.auth import logout_router as auth_logout_router
from app.api.v1.auth import public_router as auth_public_router
from app.api.v1.auth import router as auth_router
from app.api.v1.conversations import router as conversations_router
from app.api.v1.health import router as health_router
from app.api.v1.staff import router as staff_router

__all__ = ["v1_router"]

v1_router = APIRouter()
v1_router.include_router(health_router)
v1_router.include_router(auth_public_router)
v1_router.include_router(auth_router)
v1_router.include_router(auth_logout_router)
v1_router.include_router(conversations_router)
v1_router.include_router(staff_router)
