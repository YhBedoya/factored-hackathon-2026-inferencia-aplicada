"""Login, `/me`, session decode/revoke and logout (D2, D6, D9).

`login()` is the only place the raw `document_number` from a request body
touches a log line, an exception or a lookup key -- and it never does: only
the HMAC `login_key` (and its 12-hex-character prefix) ever crosses into a
`structlog` event, an `AccountStore` call or a `LoginLimiter` key (D2).
`AccountStore` and `LoginLimiter` are both `Protocol`s over the real
Redis/repository-backed calls so a test can inject in-file fakes without a
DB or Redis (`test_login_pii.py`); the API path always gets the default,
repository/Redis-backed implementations.

`LoginLimiter` is D7's rate limit: a Redis counter keyed exactly
`rl:login:<login_key>`, with no product-code prefix (unlike this app's other
Redis keys, e.g. `turn:<conversation_id>` -- `06` doesn't require one, and
D7 spells the key out literally). It is checked *before* the password is
verified, so a right password while throttled still gets `429`, and it is
only ever incremented, never reset, so a login success doesn't buy back
attempts within the window.

See `docs/specs/d2-a-login-read-tools-api.md` D2, D6, D7, D9.
"""

import hmac
from datetime import UTC, datetime
from typing import Protocol

import structlog

from app.core.config import Settings, get_settings
from app.core.redis import get_redis
from app.domains.customers import service as customers_service
from app.domains.identity import repository
from app.domains.identity.models import (
    LoginRequest,
    MeResponse,
    Session,
    StaffLoginRequest,
    StaffMeResponse,
    require_customer_id,
)
from app.domains.identity.passwords import (
    login_key,
    login_key_prefix,
    staff_login_key,
    verify_password,
)
from app.domains.identity.repository import AccountRow
from app.domains.identity.tokens import InvalidToken, TokenClaims, decode_token, issue_token

__all__ = [
    "AccountStore",
    "InvalidCredentials",
    "LoginLimiter",
    "OtpInvalid",
    "SessionExpired",
    "TooManyAttempts",
    "login",
    "logout",
    "me",
    "mint_session_for_customer",
    "refresh",
    "session_from_token",
    "staff_login",
    "staff_me",
    "verify_otp",
]

_logger = structlog.get_logger()

# Constant on purpose (D2): an unknown identifier and a wrong password must
# look identical to the caller, so the message never hints at which one it was.
_INVALID_CREDENTIALS_MESSAGE = "invalid document number or password"

_FOUR_BULLETS = "•" * 4


class InvalidCredentials(Exception):
    """Login failed: unknown `login_key`, wrong password, or an inactive
    account (D6). Always the same message (see `_INVALID_CREDENTIALS_MESSAGE`).
    """


class SessionExpired(Exception):
    """The `session` cookie doesn't decode to a live session: missing,
    invalid, expired or revoked (D6). A route turns this into `401
    session_expired` (ADR-025).
    """


class TooManyAttempts(Exception):
    """The `rl:login:<login_key>` counter is already at `login_max_failures`
    (D7). A route turns this into `429 too_many_attempts`, even when the
    password in this same request is correct.

    `verify_otp` (D3-A4) raises this same exception once `rl:otp:<account_id>`
    hits the limit, for the same reason: `429`, even for the right code.
    """


class OtpInvalid(Exception):
    """`verify_otp`'s code didn't match `settings.demo_otp_code` (D3-A4 D5).
    The code itself never reaches this message (ADR-008): only `OtpInvalid()`
    with no argument is ever raised.
    """


class AccountStore(Protocol):
    """The `identity.repository` surface `login()` and friends need,
    narrowed to a `Protocol` so `test_login_pii.py` can inject an in-file
    fake with no database.
    """

    async def get_account_by_login_key(self, login_key: str) -> AccountRow | None: ...

    async def get_account_by_customer_id(self, customer_id: str) -> AccountRow | None: ...

    async def revoke_token(self, jti: str, expires_at: datetime) -> None: ...

    async def is_revoked(self, jti: str) -> bool: ...


class _RepositoryAccountStore:
    """The default `AccountStore`: a thin pass-through to `repository`."""

    async def get_account_by_login_key(self, login_key: str) -> AccountRow | None:
        return await repository.get_account_by_login_key(login_key)

    async def get_account_by_customer_id(self, customer_id: str) -> AccountRow | None:
        return await repository.get_account_by_customer_id(customer_id)

    async def revoke_token(self, jti: str, expires_at: datetime) -> None:
        await repository.revoke_token(jti, expires_at)

    async def is_revoked(self, jti: str) -> bool:
        return await repository.is_revoked(jti)


_default_store = _RepositoryAccountStore()

_RATE_LIMIT_KEY_PREFIX = "rl:login:"


class LoginLimiter(Protocol):
    """The D7 rate-limit counter behind `login()`. `key` is always the full
    `rl:login:<login_key>` string -- callers never pass a bare `login_key`
    and the limiter itself never adds a prefix. Narrowed to a `Protocol` so
    `test_login_pii.py` can inject an in-file fake that records every key it
    was called with, with no Redis.
    """

    async def get_failures(self, key: str) -> int: ...

    async def record_failure(self, key: str, *, window_seconds: int) -> None: ...


class _RedisLoginLimiter:
    """The default `LoginLimiter`: a plain Redis `INCR` counter, `EXPIRE`d
    only on its first increment so a later failure in the same window
    doesn't push the deadline back out (D7).
    """

    async def get_failures(self, key: str) -> int:
        value = await get_redis().get(key)
        return int(value) if value is not None else 0

    async def record_failure(self, key: str, *, window_seconds: int) -> None:
        count = await get_redis().incr(key)
        if count == 1:
            await get_redis().expire(key, window_seconds)


_default_limiter = _RedisLoginLimiter()


async def login(
    req: LoginRequest,
    *,
    store: AccountStore | None = None,
    limiter: LoginLimiter | None = None,
    settings: Settings | None = None,
) -> Session:
    """Verify `req` against the account keyed by its `login_key` (D1, D2, D6),
    behind the D7 rate limit.

    Requires `status == "active"` and `role == "customer"` (D3): a staff
    row that somehow matched this `login_key` is treated exactly like an
    unknown account. Every failure path -- unknown `login_key`, wrong role,
    inactive account, wrong password -- logs `auth.login_failed` with only
    `login_key_prefix`, counts against the `rl:login:<login_key>` limit, and
    raises the same `InvalidCredentials`, so a caller can't distinguish
    "no such account" from "wrong password". Once that counter reaches
    `settings.login_max_failures`, every further attempt -- including one
    with the right password -- logs `auth.login_throttled` and raises
    `TooManyAttempts` instead, without touching the counter or the account
    store again.
    """

    store = store or _default_store
    limiter = limiter or _default_limiter
    settings = settings or get_settings()

    key = login_key(req.document_type, req.document_number, hmac_key=settings.identity_hmac_key)
    prefix = login_key_prefix(key)
    rate_limit_key = f"{_RATE_LIMIT_KEY_PREFIX}{key}"

    failures = await limiter.get_failures(rate_limit_key)
    if failures >= settings.login_max_failures:
        _logger.warning("auth.login_throttled", login_key_prefix=prefix)
        raise TooManyAttempts(f"too many failed attempts for {prefix}")

    account = await store.get_account_by_login_key(key)
    if (
        account is None
        or account.status != "active"
        or account.role != "customer"
        or not verify_password(req.password, account.password_hash)
    ):
        await limiter.record_failure(rate_limit_key, window_seconds=settings.login_window_seconds)
        _logger.warning("auth.login_failed", login_key_prefix=prefix)
        raise InvalidCredentials(_INVALID_CREDENTIALS_MESSAGE)

    _logger.info(
        "auth.login_succeeded", login_key_prefix=prefix, account_id=str(account.account_id)
    )
    return Session(
        account_id=account.account_id,
        role="customer",
        customer_id=account.customer_id,
        step_up_at=None,
    )


async def staff_login(
    req: StaffLoginRequest,
    *,
    store: AccountStore | None = None,
    limiter: LoginLimiter | None = None,
    settings: Settings | None = None,
) -> Session:
    """Verify `req` against the account keyed by `staff_login_key(req.username)`
    (D3), behind the same D7 rate limit as `login()`.

    Requires `status == "active"` and `role == "agent"`: a customer row
    that somehow matched this key is treated exactly like an unknown staff
    account. Same failure shape as `login()` -- one `InvalidCredentials`
    message, `429` checked first, and only `login_key_prefix` ever logged.
    """

    store = store or _default_store
    limiter = limiter or _default_limiter
    settings = settings or get_settings()

    key = staff_login_key(req.username, hmac_key=settings.identity_hmac_key)
    prefix = login_key_prefix(key)
    rate_limit_key = f"{_RATE_LIMIT_KEY_PREFIX}{key}"

    failures = await limiter.get_failures(rate_limit_key)
    if failures >= settings.login_max_failures:
        _logger.warning("auth.login_throttled", login_key_prefix=prefix)
        raise TooManyAttempts(f"too many failed attempts for {prefix}")

    account = await store.get_account_by_login_key(key)
    if (
        account is None
        or account.status != "active"
        or account.role != "agent"
        or not verify_password(req.password, account.password_hash)
    ):
        await limiter.record_failure(rate_limit_key, window_seconds=settings.login_window_seconds)
        _logger.warning("auth.login_failed", login_key_prefix=prefix)
        raise InvalidCredentials(_INVALID_CREDENTIALS_MESSAGE)

    _logger.info(
        "auth.login_succeeded", login_key_prefix=prefix, account_id=str(account.account_id)
    )
    return Session(
        account_id=account.account_id,
        role="agent",
        customer_id=None,
        step_up_at=None,
    )


_OTP_RATE_LIMIT_KEY_PREFIX = "rl:otp:"


async def verify_otp(
    session: Session,
    code: str,
    *,
    limiter: LoginLimiter | None = None,
    settings: Settings | None = None,
) -> Session:
    """`POST /auth/otp/verify` (D3-A4 D4, D5): step `session` up once `code`
    matches `settings.demo_otp_code`, in constant time. An empty configured
    code never matches, so an unconfigured demo box fails closed.

    Reuses the D7 rate-limit shape, keyed `rl:otp:<account_id>` instead of a
    login key (there's no document number to hash post-login), and checked
    *first*: once the counter is at `settings.login_max_failures`, every
    further call raises `TooManyAttempts`, even with the right code, without
    touching the limiter again. A miss records a failure and raises
    `OtpInvalid`; a match returns `session` with a fresh `step_up_at`, and
    nothing else about it changes. `auth.otp_failed` / `auth.otp_verified`
    log only `account_id` -- the code itself never reaches a log line or an
    exception message.
    """

    limiter = limiter or _default_limiter
    settings = settings or get_settings()

    rate_limit_key = f"{_OTP_RATE_LIMIT_KEY_PREFIX}{session.account_id}"
    failures = await limiter.get_failures(rate_limit_key)
    if failures >= settings.login_max_failures:
        _logger.warning("auth.otp_throttled", account_id=str(session.account_id))
        raise TooManyAttempts(f"too many OTP attempts for account {session.account_id}")

    matched = bool(settings.demo_otp_code) and hmac.compare_digest(
        code.encode(), settings.demo_otp_code.encode()
    )
    if not matched:
        await limiter.record_failure(rate_limit_key, window_seconds=settings.login_window_seconds)
        _logger.warning("auth.otp_failed", account_id=str(session.account_id))
        raise OtpInvalid("otp code did not match")

    _logger.info("auth.otp_verified", account_id=str(session.account_id))
    return session.model_copy(update={"step_up_at": datetime.now(UTC)})


async def me(session: Session) -> MeResponse:
    """`GET /auth/me` and the login response body (D9). The masked
    `login_hint` and the first-name-only `display_name` are formatted here,
    in code, never by the LLM (R4).
    """

    profile = await customers_service.get_login_profile(require_customer_id(session))
    hint = f"{profile.document_type} {_FOUR_BULLETS}{profile.document_last3}"
    return MeResponse(
        role="customer",
        login_hint=hint,
        display_name=profile.first_name,
        country=profile.country,
        customer_status=profile.customer_status,
    )


async def staff_me(session: Session) -> StaffMeResponse:
    """`GET /staff/me` (D3, D5): the display name for this agent session's
    own `account_id`. Never takes a username as an argument -- like `me()`,
    it only ever reflects the caller's own session back.

    A missing account or `display_name` means the row behind an
    already-valid token was deleted or never provisioned correctly; that is
    a stale session, not a bad credential, so it raises `SessionExpired`
    the same way a revoked token does.
    """

    account = await repository.get_account_by_id(session.account_id)
    if account is None or account.display_name is None:
        raise SessionExpired("staff account no longer exists")
    return StaffMeResponse(role="agent", display_name=account.display_name)


async def session_from_token(token: str) -> tuple[Session, TokenClaims]:
    """Decode `token` and check it isn't revoked (D6). Any failure --
    signature, expiry, or a live `identity.revoked_tokens` row -- is a
    `SessionExpired`.
    """

    try:
        claims = decode_token(token, secret=get_settings().jwt_secret)
    except InvalidToken as exc:
        raise SessionExpired("session token is invalid or expired") from exc
    if await repository.is_revoked(claims.jti):
        raise SessionExpired("session token was revoked")
    return claims.to_session(), claims


async def logout(claims: TokenClaims) -> None:
    """Revoke `claims.jti` until its own expiry (D6)."""

    await repository.revoke_token(claims.jti, claims.exp)


async def refresh(token: str) -> tuple[Session, str, TokenClaims]:
    """`POST /auth/refresh` (D6): re-issue `token` with a new `jti` and
    `exp` once `session_from_token` has confirmed it still decodes, hasn't
    expired and isn't revoked -- any of those is the same `SessionExpired`
    a route turns into `401 session_expired`. The spec doesn't ask this to
    revoke the old `jti`, so it doesn't; both issuances stay valid until
    their own `exp` (or an explicit logout).
    """

    session, _claims = await session_from_token(token)
    settings = get_settings()
    new_token, new_claims = issue_token(
        session, secret=settings.jwt_secret, ttl_minutes=settings.session_ttl_minutes
    )
    return session, new_token, new_claims


async def mint_session_for_customer(customer_id: str) -> Session:
    """`POST /test-idp/sessions` (D8, eval only): a session for `customer_id`
    with no password check, the one place `customer_id` arrives as an
    argument (never mounted outside `APP_ENV=eval`).
    """

    account = await repository.get_account_by_customer_id(customer_id)
    if account is None:
        raise InvalidCredentials(_INVALID_CREDENTIALS_MESSAGE)
    # `customer_id` (the argument that found `account`) is already the
    # narrowed `str`, unlike `account.customer_id` (D4: nullable on the
    # row, for the staff rows that share this table).
    return Session(
        account_id=account.account_id,
        role="customer",
        customer_id=customer_id,
        step_up_at=None,
    )
