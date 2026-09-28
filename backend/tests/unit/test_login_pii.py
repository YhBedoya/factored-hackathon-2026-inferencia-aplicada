"""`identity.service.login` PII contract (D2). See `docs/specs/d2-a-login-read-tools-api.md`
D2 and §"Test list" -> `test_login_pii.py`.

`asyncio.run` drives the coroutine since this project has no async test
runner (only sync pytest). The `AccountStore` here is an in-file fake (a
`Protocol` needs no base class), not a mock, and never touches a database.

T15 extends this same test with the rate-limit key assertion (D7): the
Redis counter key `rl:login:<login_key>` must carry the same HMAC form as
`login_key_prefix` here, never the raw document number.
"""

import asyncio
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from structlog.testing import capture_logs

from app.core.config import Settings
from app.domains.identity.models import LoginRequest
from app.domains.identity.passwords import (
    hash_password,
    login_key,
    login_key_prefix,
    normalize_document_number,
)
from app.domains.identity.repository import AccountRow
from app.domains.identity.service import InvalidCredentials, login
from app.main import create_app

_SETTINGS = Settings(identity_hmac_key="k" * 32, _env_file=None)

_DOCUMENT_TYPE = "CC"
_KNOWN_DOCUMENT_NUMBER = "DOC-TF-0000001"
_UNKNOWN_DOCUMENT_NUMBER = "DOC-TF-9999999"
_PASSWORD = "p" * 12  # fake, test-only
_WRONG_PASSWORD = "w" * 12  # fake, test-only

_KNOWN_LOGIN_KEY = login_key(
    _DOCUMENT_TYPE, _KNOWN_DOCUMENT_NUMBER, hmac_key=_SETTINGS.identity_hmac_key
)
_UNKNOWN_LOGIN_KEY = login_key(
    _DOCUMENT_TYPE, _UNKNOWN_DOCUMENT_NUMBER, hmac_key=_SETTINGS.identity_hmac_key
)

_KNOWN_ACCOUNT = AccountRow(
    account_id=uuid4(),
    role="customer",
    customer_id="CUST-0000001",
    password_hash=hash_password(_PASSWORD),
    status="active",
)


class _FakeAccountStore:
    """One account, keyed by `_KNOWN_LOGIN_KEY`. The other three
    `AccountStore` methods aren't exercised by `login()` and are never
    called here.
    """

    async def get_account_by_login_key(self, login_key: str) -> AccountRow | None:
        return _KNOWN_ACCOUNT if login_key == _KNOWN_LOGIN_KEY else None

    async def get_account_by_customer_id(self, customer_id: str) -> AccountRow | None:
        raise NotImplementedError

    async def revoke_token(self, jti: str, expires_at: object) -> None:
        raise NotImplementedError

    async def is_revoked(self, jti: str) -> bool:
        raise NotImplementedError


class _FakeLoginLimiter:
    """Never throttles (`get_failures` always `0`); just records every key
    `login()` calls it with, so the test can check the key's shape (D7)
    without touching Redis.
    """

    def __init__(self) -> None:
        self.keys: list[str] = []

    async def get_failures(self, key: str) -> int:
        self.keys.append(key)
        return 0

    async def record_failure(self, key: str, *, window_seconds: int) -> None:
        self.keys.append(key)


def test_document_number_never_logged_or_keyed() -> None:
    store = _FakeAccountStore()
    limiter = _FakeLoginLimiter()

    wrong_password_req = LoginRequest(
        document_type=_DOCUMENT_TYPE,
        document_number=_KNOWN_DOCUMENT_NUMBER,
        password=_WRONG_PASSWORD,
    )
    unknown_document_req = LoginRequest(
        document_type=_DOCUMENT_TYPE, document_number=_UNKNOWN_DOCUMENT_NUMBER, password=_PASSWORD
    )

    with capture_logs() as logs:
        with pytest.raises(InvalidCredentials):
            asyncio.run(login(wrong_password_req, store=store, limiter=limiter, settings=_SETTINGS))
        with pytest.raises(InvalidCredentials):
            asyncio.run(
                login(unknown_document_req, store=store, limiter=limiter, settings=_SETTINGS)
            )

    assert len(logs) == 2
    wrong_password_event, unknown_document_event = logs

    assert wrong_password_event["login_key_prefix"] == login_key_prefix(_KNOWN_LOGIN_KEY)
    assert unknown_document_event["login_key_prefix"] == login_key_prefix(_UNKNOWN_LOGIN_KEY)

    # D7: `get_failures` then `record_failure` each call, both keyed
    # `rl:login:<login_key>`, with no separate prefix of their own.
    assert limiter.keys == [
        f"rl:login:{_KNOWN_LOGIN_KEY}",
        f"rl:login:{_KNOWN_LOGIN_KEY}",
        f"rl:login:{_UNKNOWN_LOGIN_KEY}",
        f"rl:login:{_UNKNOWN_LOGIN_KEY}",
    ]

    forbidden = (
        _KNOWN_DOCUMENT_NUMBER,
        normalize_document_number(_KNOWN_DOCUMENT_NUMBER),
        _UNKNOWN_DOCUMENT_NUMBER,
        normalize_document_number(_UNKNOWN_DOCUMENT_NUMBER),
        _PASSWORD,
        _WRONG_PASSWORD,
        _KNOWN_LOGIN_KEY,
        _UNKNOWN_LOGIN_KEY,
    )
    for event in logs:
        for value in event.values():
            rendered = str(value)
            for banned in forbidden:
                assert banned not in rendered
    for key in limiter.keys:
        assert _KNOWN_DOCUMENT_NUMBER not in key
        assert normalize_document_number(_KNOWN_DOCUMENT_NUMBER) not in key
        assert _UNKNOWN_DOCUMENT_NUMBER not in key
        assert normalize_document_number(_UNKNOWN_DOCUMENT_NUMBER) not in key


def test_validation_error_does_not_echo_body() -> None:
    """A `/auth/login` body that fails validation must never echo back in
    the `422` response (D2): FastAPI's default per-error `input` is a raw
    copy of the submitted body, document number or password included. No
    `with` block: the app-wide `RequestValidationError` handler runs before
    the lifespan would matter, so this never needs a DB, Redis or LLM key.
    """

    client = TestClient(create_app())
    document_number = "DOC-NEVER-ECHOED-0000001"
    password = "never-echoed-password-9"

    missing_password = client.post(
        "/api/v1/auth/login",
        json={"document_type": "CC", "document_number": document_number},
    )
    assert missing_password.status_code == 422
    assert document_number not in missing_password.text
    assert password not in missing_password.text

    missing_document_number = client.post(
        "/api/v1/auth/login",
        json={"document_type": "CC", "password": password},
    )
    assert missing_document_number.status_code == 422
    assert document_number not in missing_document_number.text
    assert password not in missing_document_number.text
