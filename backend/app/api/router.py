"""Top-level API router: mounts the versioned routers `app.main` includes.

`app.main` includes only `api_router`, so a future `v2` package plugs in here
without touching `app.main`.
"""

from fastapi import APIRouter

from app.api.v1 import v1_router

__all__ = ["api_router"]

api_router = APIRouter()
api_router.include_router(v1_router, prefix="/api/v1")
