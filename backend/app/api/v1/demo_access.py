"""Judges' quick-access routes (ADR-036): `GET /demo/catalog`,
`POST /demo/sessions/customer`, `POST /demo/sessions/staff`.

`create_app()` (`app/main.py`) mounts `router` under `/api/v1` only when
`DEMO_QUICK_LOGIN=true`; with the flag off every path here is a 404 and the
landing page hides its quick-access button. Like `auth.public_router` and
`test_idp.py`, the router is public and CSRF-exempt: there is no session
cookie yet to double-submit against.

No route takes `customer_id` (R1): a customer session is minted only for a
`persona_id` listed in `eval/demo_personas.yaml`, and the staff session is
always the seeded `admin`. No password ever reaches the browser.
"""

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, ConfigDict

from app.api.v1.auth import _set_auth_cookies
from app.core.config import Settings, get_settings
from app.core.errors import NotFound
from app.domains.identity import demo_access
from app.domains.identity import service as identity_service
from app.domains.identity.demo_access import DemoPersona
from app.domains.identity.models import MeResponse, Session, StaffMeResponse
from app.domains.identity.tokens import issue_token, new_csrf_token

__all__ = ["router"]

router = APIRouter(prefix="/demo")

# The one staff account the quick access opens (seeded by `provision.py`).
_DEMO_STAFF_USERNAME = "admin"


class DemoLinks(BaseModel):
    repo: str | None
    docs: str | None


class DemoCatalog(BaseModel):
    personas: list[DemoPersona]
    otp_code: str | None
    links: DemoLinks


class DemoCustomerSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    persona_id: str


def _issue(response: Response, session: Session, settings: Settings) -> None:
    token, _claims = issue_token(
        session, secret=settings.jwt_secret, ttl_minutes=settings.session_ttl_minutes
    )
    _set_auth_cookies(response, token=token, csrf_token=new_csrf_token(), settings=settings)


@router.get("/catalog")
async def get_catalog(response: Response) -> DemoCatalog:
    """The personas, the demo OTP code and the evaluation links."""

    response.headers["Cache-Control"] = "no-store"
    settings = get_settings()
    return DemoCatalog(
        personas=await demo_access.list_demo_personas(),
        otp_code=settings.demo_otp_code or None,
        links=DemoLinks(repo=settings.demo_repo_url or None, docs=settings.demo_docs_url or None),
    )


@router.post("/sessions/customer", response_model=MeResponse)
async def create_customer_session(
    body: DemoCustomerSessionRequest, response: Response
) -> MeResponse:
    """Log in as a demo persona; same cookies and body as `/auth/login`."""

    settings = get_settings()
    try:
        customer_id = demo_access.resolve_customer_id(body.persona_id)
        session = await identity_service.mint_session_for_customer(customer_id)
    except (NotFound, identity_service.InvalidCredentials) as exc:
        raise HTTPException(status_code=404, detail="not_found") from exc
    _issue(response, session, settings)
    return await identity_service.me(session)


@router.post("/sessions/staff", response_model=StaffMeResponse)
async def create_staff_session(response: Response) -> StaffMeResponse:
    """Log in as the seeded admin; same cookies and body as
    `/auth/staff/login`.
    """

    settings = get_settings()
    try:
        session = await identity_service.mint_session_for_staff(
            _DEMO_STAFF_USERNAME, settings=settings
        )
    except identity_service.InvalidCredentials as exc:
        raise HTTPException(status_code=404, detail="not_found") from exc
    _issue(response, session, settings)
    return await identity_service.staff_me(session)
