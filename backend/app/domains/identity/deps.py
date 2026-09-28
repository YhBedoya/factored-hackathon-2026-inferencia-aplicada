"""FastAPI dependencies for auth: session, role and CSRF (D6, ADR-025, R13).

`RoleGuard` is a class rather than a closure so the R13 test
(`test_r13_routes.py`) can recognize it: it walks a router's dependencies
looking for a `RoleGuard` instance and reads its `.roles`, instead of trying
to introspect an opaque function.

See `docs/specs/d2-a-login-read-tools-api.md` D6, "Contracts" -> "Dependencies",
`docs/solution-docs/04-contracts.md` §3 "Auth (ADR-025)".
"""

import hmac
from typing import Annotated

from fastapi import Depends, HTTPException, Request

from app.domains.identity.models import Session
from app.domains.identity.service import SessionExpired, session_from_token
from app.domains.identity.tokens import CSRF_COOKIE, CSRF_HEADER, SESSION_COOKIE

__all__ = ["RoleGuard", "get_session", "require_csrf", "require_role"]

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


async def get_session(request: Request) -> Session:
    """The route-level `Session` dependency (D6). Stores the decoded claims
    on `request.state.session_claims` for callers that need `jti` (logout,
    refresh). A missing, invalid, expired or revoked token is always the
    same `401 session_expired`, never a distinguishable error.
    """

    token = request.cookies.get(SESSION_COOKIE)
    if token is None:
        raise HTTPException(status_code=401, detail="session_expired")
    try:
        session, claims = await session_from_token(token)
    except SessionExpired as exc:
        raise HTTPException(status_code=401, detail="session_expired") from exc
    request.state.session_claims = claims
    return session


class RoleGuard:
    """A `Depends(require_role(...))` value. Every non-public router
    declares one at the router level (R13, ADR-025): `__call__` depends on
    `get_session` and raises `403 forbidden_role` when the session's role
    isn't in `roles`.
    """

    def __init__(self, roles: tuple[str, ...]) -> None:
        self.roles = roles

    async def __call__(self, session: Annotated[Session, Depends(get_session)]) -> Session:
        if session.role not in self.roles:
            raise HTTPException(status_code=403, detail="forbidden_role")
        return session


def require_role(*roles: str) -> RoleGuard:
    """Build the router-level role dependency for `roles` (D6, R13)."""
    return RoleGuard(roles)


async def require_csrf(request: Request) -> None:
    """Double-submit CSRF check (D6): on any method but GET/HEAD/OPTIONS,
    `X-CSRF-Token` must equal the `csrf_token` cookie, compared in constant
    time. Anything else is `403 csrf_failed`.
    """

    if request.method in _SAFE_METHODS:
        return
    header = request.headers.get(CSRF_HEADER)
    cookie = request.cookies.get(CSRF_COOKIE)
    if not header or not cookie or not hmac.compare_digest(header, cookie):
        raise HTTPException(status_code=403, detail="csrf_failed")
