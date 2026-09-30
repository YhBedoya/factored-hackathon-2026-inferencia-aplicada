"""Version-1 API router: mounts each route module under `/api/v1`."""

from fastapi import APIRouter

from app.api.v1.admin import router as admin_router
from app.api.v1.auth import public_router as auth_public_router
from app.api.v1.auth import router as auth_router
from app.api.v1.conversations import router as conversations_router
from app.api.v1.health import router as health_router
from app.api.v1.me import router as me_router
from app.api.v1.staff import router as staff_router
from app.api.v1.staff_admin import router as staff_admin_router
from app.api.v1.staff_auth import public_router as staff_auth_public_router
from app.api.v1.staff_auth import router as staff_auth_router

__all__ = ["v1_router"]

v1_router = APIRouter()
v1_router.include_router(health_router)
v1_router.include_router(auth_public_router)
v1_router.include_router(auth_router)
v1_router.include_router(conversations_router)
v1_router.include_router(me_router)
v1_router.include_router(staff_auth_public_router)
v1_router.include_router(staff_auth_router)
v1_router.include_router(staff_router)
v1_router.include_router(staff_admin_router)
v1_router.include_router(admin_router)
