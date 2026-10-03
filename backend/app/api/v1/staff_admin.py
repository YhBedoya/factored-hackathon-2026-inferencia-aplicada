"""Admin-only persona and analytics routes under `/staff` (D22).

`GET /staff/personas` lists the persona catalog and
`GET /staff/personas/{persona_id}/credentials` returns a catalog persona's
login credentials. `GET /staff/analytics/summary` returns the interaction
analytics dashboard summary. The router declares `require_role("admin")` and
`require_csrf` at the router level (R13, ADR-025), so an agent session gets
`403 forbidden_role`. It is a separate module from `staff.py` because that
router is agent+admin.

See `docs/specs/d7-a-timeline-heldout-report.md` D22.
"""

from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response

from app.core.errors import NotFound
from app.domains.analytics import dashboard
from app.domains.analytics.dashboard import AnalyticsSummary
from app.domains.identity import personas
from app.domains.identity.deps import require_csrf, require_role
from app.domains.identity.personas import PersonaCredentials, PersonaEntry

__all__ = ["router"]

router = APIRouter(
    prefix="/staff",
    dependencies=[Depends(require_role("admin")), Depends(require_csrf)],
)


@router.get("/personas")
async def list_personas() -> list[PersonaEntry]:
    return personas.load_catalog()


@router.get("/personas/{persona_id}/credentials")
async def get_persona_credentials(persona_id: str, response: Response) -> PersonaCredentials:
    # Secrets must not be cached by the browser or a proxy.
    response.headers["Cache-Control"] = "no-store"
    try:
        return await personas.get_credentials(persona_id)
    except NotFound as exc:
        raise HTTPException(status_code=404, detail="not_found") from exc


@router.get("/analytics/summary")
async def get_analytics_summary(
    date_from: date | None = None,
    date_to: date | None = None,
    language: Literal["es", "pt"] | None = None,
    country: Literal["MX", "CO", "AR"] | None = None,
    source: Literal["all", "real", "mock"] = "all",
) -> AnalyticsSummary:
    try:
        filters = dashboard.resolve_filters(date_from, date_to, language, country, source)
    except dashboard.InvalidDateRange as exc:
        raise HTTPException(status_code=422, detail="invalid_date_range") from exc
    try:
        return await dashboard.get_summary(filters)
    except dashboard.AnalyticsTimeout as exc:
        raise HTTPException(status_code=503, detail="analytics_timeout") from exc
