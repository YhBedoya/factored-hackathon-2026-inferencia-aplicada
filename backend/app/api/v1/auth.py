"""Auth routes (D2, D6, D7, D9): `POST /auth/login`, `POST /auth/logout`,
`GET /auth/me`, `POST /auth/otp/verify` (D3-A4).

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
nothing left for `require_role` to check -- except for one explicit role
check after decoding (D4-B D5): a staff session gets `403 forbidden_role`
instead of a re-issued cookie pair, since staff sessions never refresh here.

`POST /auth/otp/verify` (D3-A4 D5) sits on `router`, not `public_router`:
unlike refresh, stepping up needs a live, role-checked session to step up.
It mirrors `refresh()`'s re-issue shape exactly -- new `session` and
`csrf_token` cookies, the old token left unrevoked -- except the re-issued
session carries a fresh `step_up_at` instead of the same one.

See `docs/specs/d2-a-login-read-tools-api.md` "Contracts" -> "HTTP",
D6, D7, D9 and `docs/specs/d3-a-guardrails-write-path.md` D4, D5.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict

from app.api.v1.conversations import get_owned_conversation
from app.core.config import Settings, get_settings
from app.core.telemetry import get_trace_id
from app.domains.conversation.runner import TurnInProgress, checkpointed_otp_pause, start_turn
from app.domains.conversation.store import ConversationRow
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
from app.domains.policy.registry import get_policies

__all__ = ["OtpVerifyRequest", "public_router", "router"]


class OtpVerifyRequest(BaseModel):
    """`POST /auth/otp/verify` body (D3-A4 D5). `extra="forbid"` so a
    mistyped field is a `422`, not a silently ignored one.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    code: str
    conversation_id: UUID | None = None


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
    same as the spec's "public (needs a valid cookie + CSRF)" -- except that
    a staff session gets `403 forbidden_role` (D4-B D5).
    """

    settings = get_settings()
    token = request.cookies.get(SESSION_COOKIE)
    if token is None:
        raise HTTPException(status_code=401, detail="session_expired")
    try:
        session, new_token, _claims = await identity_service.refresh(token)
    except identity_service.SessionExpired as exc:
        raise HTTPException(status_code=401, detail="session_expired") from exc
    if session.role != "customer":
        raise HTTPException(status_code=403, detail="forbidden_role")

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


async def _hand_off_if_paused(
    request: Request, session: Session, conversation: ConversationRow
) -> None:
    """Start the `step_up_failed` turn when `conversation` is open, in bot
    mode and at an OTP pause; raise `429 otp_handoff` once it is scheduled.
    Returns silently when there is nothing to hand off (S2 D27).
    """

    if conversation.status == "closed" or conversation.mode != "bot":
        return
    host = request.app.state.turn_host
    if await checkpointed_otp_pause(host, conversation.id) is None:
        return
    try:
        await start_turn(
            host,
            session=session,
            conversation_id=conversation.id,
            trace_id=get_trace_id(),
            resume="step_up_failed",
        )
    except TurnInProgress as exc:
        raise HTTPException(status_code=429, detail="too_many_attempts") from exc
    await identity_service.reset_otp_failures(session)
    raise HTTPException(status_code=429, detail="otp_handoff")


@router.post("/auth/otp/verify", response_model=MeResponse)
async def verify_otp(
    req: OtpVerifyRequest,
    request: Request,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
) -> MeResponse:
    """Step `session` up with a demo OTP code (D3-A4 D4, D5), and re-issue
    the session and CSRF cookies exactly as `refresh()` does, so the old
    token stays valid until its own `exp`. A wrong code is `401
    otp_invalid`; hitting `rl:otp:<account_id>`'s limit is `429
    too_many_attempts`, checked before the code, so it wins even when the
    code in this same request is right.

    With `conversation_id` (S2 D27) the conversation is loaded first, scoped
    to the caller (`404 not_found` before the code is checked, nothing
    recorded). If the code is wrong and brings the counter to
    `tools.step_up_max_failures`, or the counter is already there, and that
    conversation is open, in bot mode and paused at an OTP pause, the route
    starts the internal `step_up_failed` handoff turn, resets the counter
    and returns `429 otp_handoff`. A `turn_in_progress` there is `429
    too_many_attempts` with the counter kept, so the next attempt hands
    off. Every other case is the plain `401` / `429`. The handoff turn is
    server-started, so it counts toward no turn cap (A4).
    """

    settings = get_settings()
    conversation = None
    if req.conversation_id is not None:
        conversation = await get_owned_conversation(req.conversation_id, session)
    limit = get_policies().tools.step_up_max_failures
    try:
        new_session = await identity_service.verify_otp(
            session, req.code, max_failures=limit, settings=settings
        )
    except (identity_service.TooManyAttempts, identity_service.OtpInvalid) as exc:
        at_limit = isinstance(exc, identity_service.TooManyAttempts) or exc.failures >= limit
        if at_limit and conversation is not None:
            await _hand_off_if_paused(request, session, conversation)
        if isinstance(exc, identity_service.TooManyAttempts):
            raise HTTPException(status_code=429, detail="too_many_attempts") from exc
        raise HTTPException(status_code=401, detail="otp_invalid") from exc

    token, _claims = issue_token(
        new_session, secret=settings.jwt_secret, ttl_minutes=settings.session_ttl_minutes
    )
    csrf_token = new_csrf_token()
    _set_auth_cookies(response, token=token, csrf_token=csrf_token, settings=settings)
    return await identity_service.me(new_session)
