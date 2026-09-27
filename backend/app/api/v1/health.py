"""Public liveness route (D15): `GET /api/v1/health`.

`04` §3: only `/auth/login`, `/auth/refresh` and this health check are public,
so this route carries no auth or ownership dependency (R13 starts with the
first non-public route in D2). The two probes are FastAPI dependencies
(rather than being called directly) so tests can override them with
`app.dependency_overrides` and never touch a real DB or Redis.
"""

from typing import Literal

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.core.db import ping_db
from app.core.redis import ping_redis

__all__ = ["HealthResponse", "router"]

router = APIRouter()


class HealthResponse(BaseModel):
    """Body returned on both success and failure (D15): same shape either way."""

    status: Literal["ok", "degraded"]
    db: Literal["up", "down"]
    redis: Literal["up", "down"]


@router.get("/health")
async def health(
    db_up: bool = Depends(ping_db),
    redis_up: bool = Depends(ping_redis),
) -> JSONResponse:
    """`200` when DB and Redis are both up, `503` otherwise (D15)."""
    both_up = db_up and redis_up
    body = HealthResponse(
        status="ok" if both_up else "degraded",
        db="up" if db_up else "down",
        redis="up" if redis_up else "down",
    )
    return JSONResponse(status_code=200 if both_up else 503, content=body.model_dump())
