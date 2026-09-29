"""Admin routes (D4-A D16), all under `/admin` and restricted to role `admin`.

T25 adds `POST /admin/demo/reset` (`{status: "reset", duration_ms}`).

The router declares `require_role("admin")` and `require_csrf` at the router
level (R13, ADR-025), so an agent session gets `403 forbidden_role`.

See `docs/specs/d4-a-escalation-handoff-deploy.md` D16 and "Contracts" ->
"Staff API".
"""

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from app.core.config import get_settings
from app.core.demo_reset import reset_app_database
from app.domains.conversation.hosting import close_host, open_host
from app.domains.identity.deps import require_csrf, require_role

__all__ = ["router"]

router = APIRouter(
    prefix="/admin",
    dependencies=[Depends(require_role("admin")), Depends(require_csrf)],
)


class DemoResetResponse(BaseModel):
    status: str
    duration_ms: int


@router.post("/demo/reset")
async def demo_reset(request: Request) -> DemoResetResponse:
    """Recreate `latam_app` from the golden DB (D21).

    The checkpointer pool holds connections to the database being dropped, so
    the turn host is closed first and reopened in `finally`: a failed reset
    must not leave the app without a host. The failure then propagates as a 500.
    """
    old_host = request.app.state.turn_host
    await close_host(old_host)
    try:
        duration_ms = await reset_app_database()
    finally:
        request.app.state.turn_host = await open_host(get_settings().database_url, old_host.llm)
    return DemoResetResponse(status="reset", duration_ms=duration_ms)
