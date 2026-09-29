"""Staff auth routes (D4-A D16): `POST /auth/staff/login`, `GET /staff/me`,
`POST /staff/logout`.

`public_router` carries `/auth/staff/login`, public and CSRF-exempt like
`/auth/login` (there is no cookie yet to double-submit against). `router`
declares `require_role("agent", "admin")` and `require_csrf` at the router
level (R13, ADR-025), so a customer session gets `403 forbidden_role` here.

`staff_login()` keeps `429 too_many_attempts` ahead of `401
invalid_credentials`, same as `auth.login()`. A staff session never carries a
`customer_id` (R1), and no route here takes one. Passwords are never logged:
the service logs only the keyed login prefix.

See `docs/specs/d4-a-escalation-handoff-deploy.md` D16 and "Contracts" ->
"Staff auth".
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from app.api.v1.auth import _set_auth_cookies
from app.core.config import get_settings
from app.domains.identity import service as identity_service
from app.domains.identity.deps import get_session, require_csrf, require_role
from app.domains.identity.models import Session, StaffLoginRequest, StaffMeResponse
from app.domains.identity.tokens import (
    CSRF_COOKIE,
    SESSION_COOKIE,
    TokenClaims,
    issue_token,
    new_csrf_token,
)

__all__ = ["public_router", "router"]

public_router = APIRouter()
router = APIRouter(dependencies=[Depends(require_role("agent", "admin")), Depends(require_csrf)])


@public_router.post("/auth/staff/login", response_model=StaffMeResponse)
async def staff_login(req: StaffLoginRequest, response: Response) -> StaffMeResponse:
    """Verify the staff username + password, issue the session and CSRF
    cookie pair, and return the same body `GET /staff/me` would.
    """

    settings = get_settings()
    try:
        session = await identity_service.staff_login(req, settings=settings)
    except identity_service.TooManyAttempts as exc:
        raise HTTPException(status_code=429, detail="too_many_attempts") from exc
    except identity_service.InvalidCredentials as exc:
        raise HTTPException(status_code=401, detail="invalid_credentials") from exc

    token, _claims = issue_token(
        session, secret=settings.jwt_secret, ttl_minutes=settings.session_ttl_minutes
    )
    _set_auth_cookies(response, token=token, csrf_token=new_csrf_token(), settings=settings)
    return await _staff_me(session)


async def _staff_me(session: Session) -> StaffMeResponse:
    try:
        return await identity_service.staff_me(session)
    except identity_service.SessionExpired as exc:
        raise HTTPException(status_code=401, detail="session_expired") from exc


@router.get("/staff/me", response_model=StaffMeResponse)
async def staff_me(session: Annotated[Session, Depends(get_session)]) -> StaffMeResponse:
    """The staff profile for the caller's own session."""

    return await _staff_me(session)


@router.post("/staff/logout", status_code=204)
async def staff_logout(request: Request, response: Response) -> None:
    """Revoke the caller's `jti` and clear both cookies."""

    claims: TokenClaims = request.state.session_claims
    await identity_service.logout(claims)
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
