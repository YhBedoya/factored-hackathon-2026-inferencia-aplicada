"""JWT session tokens and the CSRF double-submit token (D6).

`issue_token`/`decode_token` are the only place a `Session` becomes a
signed string and back. No function here logs a token or its claims — a
route that needs to say something logs `jti` or `login_key_prefix`, never
this module's output.

See `docs/specs/d2-a-login-read-tools-api.md` D6, `docs/solution-docs/04-contracts.md` §3.
"""

import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

import jwt
from pydantic import BaseModel, ConfigDict

from app.domains.identity.models import Session

__all__ = [
    "CSRF_COOKIE",
    "CSRF_HEADER",
    "SESSION_COOKIE",
    "InvalidToken",
    "TokenClaims",
    "decode_token",
    "issue_token",
    "new_csrf_token",
]

SESSION_COOKIE = "session"
CSRF_COOKIE = "csrf_token"
CSRF_HEADER = "X-CSRF-Token"

_ALGORITHM = "HS256"


class InvalidToken(Exception):
    """A `session` cookie that doesn't decode to a live session: bad
    signature, expired, or missing/malformed claims (D6). Callers turn this
    into `401 session_expired` (ADR-025); it never reaches a route as a raw
    `jwt` exception.
    """


class TokenClaims(BaseModel):
    """The decoded JWT payload. `to_session()` is the only place a raw
    claims set becomes the `Session` the rest of the app trusts.
    """

    model_config = ConfigDict(frozen=True)

    sub: UUID
    role: Literal["customer", "agent"]
    customer_id: str | None
    step_up_at: datetime | None
    jti: str
    exp: datetime

    def to_session(self) -> Session:
        return Session(
            account_id=self.sub,
            role=self.role,
            customer_id=self.customer_id,
            step_up_at=self.step_up_at,
        )


def issue_token(session: Session, *, secret: str, ttl_minutes: int) -> tuple[str, TokenClaims]:
    """Issue an HS256 token for `session`. A fresh `jti` per call so logout
    and refresh can revoke exactly one issuance (D6).
    """

    claims = TokenClaims(
        sub=session.account_id,
        role=session.role,
        customer_id=session.customer_id,
        step_up_at=session.step_up_at,
        jti=str(uuid.uuid4()),
        exp=datetime.now(UTC) + timedelta(minutes=ttl_minutes),
    )
    payload = {
        "sub": str(claims.sub),
        "role": claims.role,
        "customer_id": claims.customer_id,
        "step_up_at": claims.step_up_at.isoformat() if claims.step_up_at else None,
        "jti": claims.jti,
        "exp": claims.exp,
    }
    token = jwt.encode(payload, secret, algorithm=_ALGORITHM)
    return token, claims


def decode_token(token: str, *, secret: str) -> TokenClaims:
    """Verify the signature and expiry, then rebuild `TokenClaims`. Any
    failure — bad signature, expiry, a missing or malformed claim — is an
    `InvalidToken`.
    """

    try:
        payload = jwt.decode(token, secret, algorithms=[_ALGORITHM])
        return TokenClaims(
            sub=payload["sub"],
            role=payload["role"],
            customer_id=payload["customer_id"],
            step_up_at=payload.get("step_up_at"),
            jti=payload["jti"],
            exp=payload["exp"],
        )
    except (jwt.PyJWTError, KeyError, ValueError, TypeError) as exc:
        raise InvalidToken("invalid or expired session token") from exc


def new_csrf_token() -> str:
    """A fresh double-submit CSRF token (D6)."""

    return secrets.token_urlsafe(32)
