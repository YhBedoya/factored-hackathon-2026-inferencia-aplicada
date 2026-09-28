"""Eval-only test IdP route (D8, ADR-025): `POST /test-idp/sessions`.

This is the **one route in the whole API that takes `customer_id` as an
argument** (R1's single, deliberate exception): it mints a session without a
password check, so `make chat-api PERSONA=<customer_id>` and eval harnesses
can act as any persona without knowing its generated password. `create_app()`
(`app/main.py`) mounts `router` under `/api/v1` only when
`get_settings().app_env == "eval"` -- it is never reachable in `dev` or
`prod`, and `test_r1_routes.py` asserts that directly.

`router` carries no `require_role`/`require_csrf` dependency, so -- like
`auth.py`'s `public_router` -- it is CSRF-exempt: there is no session cookie
yet to double-submit against. The cookie-setting shape mirrors `auth.py`'s
`_set_auth_cookies` (mirror, not import, same convention `registry.py` and
`runner.py` set: `auth.py` is untouched by this task).

See `docs/specs/d2-a-login-read-tools-api.md` D6, D8, "Contracts" -> "HTTP".
"""

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, ConfigDict

from app.core.config import Settings, get_settings
from app.domains.identity import service as identity_service
from app.domains.identity.models import MeResponse
from app.domains.identity.tokens import (
    CSRF_COOKIE,
    SESSION_COOKIE,
    issue_token,
    new_csrf_token,
)

__all__ = ["router"]

router = APIRouter()


class TestIdPRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customer_id: str


def _set_auth_cookies(
    response: Response, *, token: str, csrf_token: str, settings: Settings
) -> None:
    """Same cookie shape `auth.py`'s login sets (D6): `SameSite=Lax`,
    `Secure` only in prod, a `max_age` tied to `session_ttl_minutes`, path
    `/`.
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


@router.post("/test-idp/sessions", response_model=MeResponse)
async def create_test_session(body: TestIdPRequest, response: Response) -> MeResponse:
    """Mint a session for `body.customer_id` with no password check (D8),
    set the same cookies `/auth/login` would, and return the same
    `MeResponse` body. An unknown customer is `404 not_found`.
    """

    settings = get_settings()
    try:
        session = await identity_service.mint_session_for_customer(body.customer_id)
    except identity_service.InvalidCredentials as exc:
        raise HTTPException(status_code=404, detail="not_found") from exc

    token, _claims = issue_token(
        session, secret=settings.jwt_secret, ttl_minutes=settings.session_ttl_minutes
    )
    csrf_token = new_csrf_token()
    _set_auth_cookies(response, token=token, csrf_token=csrf_token, settings=settings)
    return await identity_service.me(session)
