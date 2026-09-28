"""Auth routes (D2, D6, D7, D9): `POST /auth/login`, `POST /auth/logout`,
`GET /auth/me`.

`public_router` carries `/auth/login`, the one non-GET route CSRF never
guards (D6): there is no cookie yet to double-submit against. `router`
declares `require_role("customer")` and `require_csrf` at the *router*
level (R13, ADR-025), not per-route, so a future route added here can't
forget either check. `require_csrf` is a no-op on GET, so mounting it next
to `GET /auth/me` costs nothing.

`login()` turns `identity_service.TooManyAttempts` (D7's rate limit) into
`429 too_many_attempts` before `InvalidCredentials` into `401
invalid_credentials` -- the two never collapse into one status, since a
caller past the rate limit needs to know to stop retrying rather than to
try a different password.

No route here takes `customer_id` (R1): it always comes from the `Session`
`get_session()` builds off the `session` cookie. `POST /auth/refresh` sits
on `public_router` too (D6): it proves the caller through the `session`
cookie plus CSRF, not a role dependency, since a session past `exp` has
nothing left for `require_role` to check.

See `docs/specs/d2-a-login-read-tools-api.md` "Contracts" -> "HTTP",
D6, D7, D9.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from app.core.config import Settings, get_settings
from app.domains.identity import service as identity_service
from app.domains.identity.deps import get_session, require_csrf, require_role
from app.domains.identity.models import LoginRequest, MeResponse, Session
from app.domains.identity.tokens import (
    CSRF_COOKIE,
    SESSION_COOKIE,
    TokenClaims,
    issue_token,
    new_csrf_token,
)

__all__ = ["public_router", "router"]

public_router = APIRouter()
router = APIRouter(dependencies=[Depends(require_role("customer")), Depends(require_csrf)])


def _set_auth_cookies(
    response: Response, *, token: str, csrf_token: str, settings: Settings
) -> None:
    """Set the `session` (httpOnly) and `csrf_token` (readable) cookies with
    the shared flags from D6: `SameSite=Lax`, `Secure` only in prod, a
    `max_age` tied to `session_ttl_minutes`, path `/`.
    """

    secure = settings.app_env == "prod"
    max_age = settings.session_ttl_minutes * 60
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=max_age,
        path="/",
        httponly=True,
        samesite="lax",
        secure=secure,
    )
    response.set_cookie(
        CSRF_COOKIE,
        csrf_token,
        max_age=max_age,
        path="/",
        httponly=False,
        samesite="lax",
        secure=secure,
    )


@public_router.post("/auth/login", response_model=MeResponse)
async def login(req: LoginRequest, response: Response) -> MeResponse:
    """Verify the document + password, issue a session and CSRF cookie pair,
    and return the same body `GET /auth/me` would (D6, D9).
    """

    settings = get_settings()
    try:
        session = await identity_service.login(req, settings=settings)
    except identity_service.TooManyAttempts as exc:
        raise HTTPException(status_code=429, detail="too_many_attempts") from exc
    except identity_service.InvalidCredentials as exc:
        raise HTTPException(status_code=401, detail="invalid_credentials") from exc

    token, _claims = issue_token(
        session, secret=settings.jwt_secret, ttl_minutes=settings.session_ttl_minutes
    )
    csrf_token = new_csrf_token()
    _set_auth_cookies(response, token=token, csrf_token=csrf_token, settings=settings)
    return await identity_service.me(session)


@public_router.post(
    "/auth/refresh", response_model=MeResponse, dependencies=[Depends(require_csrf)]
)
async def refresh(request: Request, response: Response) -> MeResponse:
    """Re-issue the session and CSRF cookies for a still-valid, unrevoked
    session (D6). No role dependency: the cookie + CSRF pair is the proof,
    same as the spec's "public (needs a valid cookie + CSRF)".
    """

    settings = get_settings()
    token = request.cookies.get(SESSION_COOKIE)
    if token is None:
        raise HTTPException(status_code=401, detail="session_expired")
    try:
        session, new_token, _claims = await identity_service.refresh(token)
    except identity_service.SessionExpired as exc:
        raise HTTPException(status_code=401, detail="session_expired") from exc

    csrf_token = new_csrf_token()
    _set_auth_cookies(response, token=new_token, csrf_token=csrf_token, settings=settings)
    return await identity_service.me(session)


@router.post("/auth/logout", status_code=204)
async def logout(request: Request, response: Response) -> None:
    """Revoke the caller's `jti` and clear both cookies (D6)."""

    claims: TokenClaims = request.state.session_claims
    await identity_service.logout(claims)
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")


@router.get("/auth/me", response_model=MeResponse)
async def me(session: Annotated[Session, Depends(get_session)]) -> MeResponse:
    """The masked profile for the caller's own session (D9)."""

    return await identity_service.me(session)
