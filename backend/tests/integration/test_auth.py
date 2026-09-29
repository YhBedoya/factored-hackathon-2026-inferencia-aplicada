"""`POST /auth/login` and `GET /auth/me` integration test (D2, D6, D7, D9),
`POST /auth/otp/verify` (D3-A4 D4, D5), and the D4-B staff split
(`POST /auth/staff/login`, `GET /staff/me`, D3-D5).

Runs against the real dev Postgres and Redis through `app_client` (D19): the
one place this card proves a request never gets back a raw document number,
a normalized one, a last name or another customer's `customer_id`, and the
one place D7's rate limit is proven end to end against a real Redis (the
key shape itself is `test_login_pii.py`'s job, with a fake).

`test_otp_verify` doesn't rely on the conftest Redis cleanup patterns for
`rl:otp:*` (T2's job elsewhere in this card): `it_accounts` mints a fresh
`account_id` per test run, so this run's `rl:otp:<account_id>` key can never
collide with a previous run's leftovers.

`test_staff_login_and_role_split` uses its own `it_staff_account` fixture,
defined here rather than in `tests/integration/conftest.py`: this is the
only test in the card that needs a `role='agent'` row, so it inserts and
tears down that one row itself, instead of widening the shared fixture file
every other integration test also depends on.

See `docs/specs/d2-a-login-read-tools-api.md` "Contracts" -> "HTTP", D2, D6,
D7, D9, `docs/specs/d3-a-guardrails-write-path.md` "Contracts" -> "HTTP",
D4, D5 and `docs/specs/d4-b-disputes-handoff-screens.md` D3-D5.
"""

import asyncio
import uuid
from collections.abc import Iterator
from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.config import get_settings
from app.core.db import get_engine
from app.domains.identity.passwords import hash_password, staff_login_key
from app.domains.identity.tokens import CSRF_HEADER, decode_token
from app.main import create_app
from tests.integration.conftest import ItAccount


@dataclass(frozen=True)
class _StaffAccount:
    """One `it_staff_account` login, in-test only, mirroring `ItAccount`."""

    username: str
    password: str
    display_name: str


async def _insert_staff_account(account: _StaffAccount) -> uuid.UUID:
    account_id = uuid.uuid4()
    login_key = staff_login_key(account.username, hmac_key=get_settings().identity_hmac_key)
    async with get_engine().begin() as conn:
        await conn.execute(
            text(
                """
                INSERT INTO identity.accounts
                    (account_id, role, customer_id, username, display_name,
                     login_key, password_hash)
                VALUES
                    (:account_id, 'agent', NULL, :username, :display_name,
                     :login_key, :password_hash)
                """
            ),
            {
                "account_id": str(account_id),
                "username": account.username,
                "display_name": account.display_name,
                "login_key": login_key,
                "password_hash": hash_password(account.password),
            },
        )
    return account_id


async def _delete_account(account_id: uuid.UUID) -> None:
    async with get_engine().begin() as conn:
        await conn.execute(
            text("DELETE FROM identity.accounts WHERE account_id = :account_id"),
            {"account_id": str(account_id)},
        )


@pytest.fixture
def it_staff_account(it_env: None) -> Iterator[_StaffAccount]:
    """One `role='agent'` row (D3): `customer_id NULL`, `username`,
    `display_name`, `login_key = staff_login_key(username, ...)`. Deletes
    its own row on teardown, the same shape `it_accounts` uses.
    """

    account = _StaffAccount(
        username="it-agente", password="it-staff-password", display_name="Agente de Prueba"
    )
    account_id = asyncio.run(_insert_staff_account(account))
    # `get_engine()` is loop-bound: this fixture's own `asyncio.run()`
    # leaves a cached engine tied to a loop that is now closed.
    get_engine.cache_clear()

    yield account

    get_engine.cache_clear()
    asyncio.run(_delete_account(account_id))
    get_engine.cache_clear()


def test_me_returns_only_own_masked_profile(
    app_client: TestClient, it_accounts: dict[str, ItAccount]
) -> None:
    account = it_accounts["CLI-TFMULTI00001"]

    login_response = app_client.post(
        "/api/v1/auth/login",
        json={
            "document_type": account.document_type,
            "document_number": account.document_number,
            "password": account.password,
        },
    )
    assert login_response.status_code == 200
    assert "session" in login_response.cookies
    assert "csrf_token" in login_response.cookies

    me_response = app_client.get("/api/v1/auth/me")
    assert me_response.status_code == 200
    assert me_response.json() == {
        "role": "customer",
        "login_hint": "CC ••••001",
        "display_name": "Prueba",
        "country": "MX",
        "customer_status": "Active",
    }

    body = me_response.text
    for leaked in (
        "DOC-TF0000001",
        "DOCTF0000001",
        "Uno",
        "CLI-TFMULTI00001",
        "CLI-TFSINGLE0002",
    ):
        assert leaked not in body

    with TestClient(create_app()) as fresh_client:
        fresh_response = fresh_client.get("/api/v1/auth/me")
    assert fresh_response.status_code == 401
    assert fresh_response.json() == {"detail": "session_expired"}


def test_five_failures_then_429(app_client: TestClient, it_accounts: dict[str, ItAccount]) -> None:
    """D7. Five wrong passwords count against the `rl:login:<login_key>`
    limit and each get `401`; the sixth attempt, even with the right
    password, gets `429` instead of being checked at all.
    """

    account = it_accounts["CLI-TFSINGLE0002"]
    wrong_login = {
        "document_type": account.document_type,
        "document_number": account.document_number,
        "password": "definitely-wrong-password",
    }

    for _ in range(5):
        response = app_client.post("/api/v1/auth/login", json=wrong_login)
        assert response.status_code == 401
        assert response.json() == {"detail": "invalid_credentials"}

    right_login = {**wrong_login, "password": account.password}
    throttled_response = app_client.post("/api/v1/auth/login", json=right_login)
    assert throttled_response.status_code == 429
    assert throttled_response.json() == {"detail": "too_many_attempts"}


def test_otp_verify(
    app_client: TestClient,
    it_accounts: dict[str, ItAccount],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D4/D5: the right `DEMO_OTP_CODE` steps the session up (the re-issued
    `session` cookie decodes with `step_up_at` set); a wrong code is `401
    otp_invalid`, five of those hit `rl:otp:<account_id>`'s limit, and the
    sixth attempt is `429 too_many_attempts` even with the right code.
    """

    monkeypatch.setenv("DEMO_OTP_CODE", "246810")
    get_settings.cache_clear()

    account = it_accounts["CLI-TFMULTI00001"]
    login_response = app_client.post(
        "/api/v1/auth/login",
        json={
            "document_type": account.document_type,
            "document_number": account.document_number,
            "password": account.password,
        },
    )
    assert login_response.status_code == 200
    csrf_token = login_response.cookies["csrf_token"]

    verify_response = app_client.post(
        "/api/v1/auth/otp/verify",
        json={"code": "246810"},
        headers={CSRF_HEADER: csrf_token},
    )
    assert verify_response.status_code == 200
    session_cookie = verify_response.cookies["session"]
    claims = decode_token(session_cookie, secret=get_settings().jwt_secret)
    assert claims.step_up_at is not None

    # A second account, still logged out at the top of this test, so the
    # verified attempt above never counts against its own rl:otp: counter.
    other_account = it_accounts["CLI-TFSINGLE0002"]
    other_login = app_client.post(
        "/api/v1/auth/login",
        json={
            "document_type": other_account.document_type,
            "document_number": other_account.document_number,
            "password": other_account.password,
        },
    )
    assert other_login.status_code == 200
    csrf_token = other_login.cookies["csrf_token"]

    for _ in range(5):
        wrong_response = app_client.post(
            "/api/v1/auth/otp/verify",
            json={"code": "000000"},
            headers={CSRF_HEADER: csrf_token},
        )
        assert wrong_response.status_code == 401
        assert wrong_response.json() == {"detail": "otp_invalid"}
        # A failure never re-issues the CSRF cookie, but the latest one
        # (login rotates it via _set_auth_cookies too) is still what's live.
        csrf_token = wrong_response.cookies.get("csrf_token", csrf_token)

    throttled_response = app_client.post(
        "/api/v1/auth/otp/verify",
        json={"code": "246810"},
        headers={CSRF_HEADER: csrf_token},
    )
    assert throttled_response.status_code == 429
    assert throttled_response.json() == {"detail": "too_many_attempts"}


def test_staff_login_and_role_split(
    app_client: TestClient,
    it_accounts: dict[str, ItAccount],
    it_staff_account: _StaffAccount,
) -> None:
    """D3-D5, R13: staff login -> `/staff/me` 200 with `display_name`; that
    session on `/conversations` -> 403; a customer session on `/staff/me` ->
    403; customer credentials on staff login -> 401.
    """

    staff_login_response = app_client.post(
        "/api/v1/auth/staff/login",
        json={"username": it_staff_account.username, "password": it_staff_account.password},
    )
    assert staff_login_response.status_code == 200
    assert staff_login_response.json() == {
        "role": "agent",
        "display_name": it_staff_account.display_name,
    }
    assert "session" in staff_login_response.cookies
    assert "csrf_token" in staff_login_response.cookies
    csrf_token = staff_login_response.cookies["csrf_token"]

    staff_me_response = app_client.get("/api/v1/staff/me")
    assert staff_me_response.status_code == 200
    assert staff_me_response.json() == {
        "role": "agent",
        "display_name": it_staff_account.display_name,
    }

    # The staff session is forbidden from the customer-only conversations
    # router (D5, R13), even with a valid CSRF pair.
    forbidden_conversation = app_client.post(
        "/api/v1/conversations", json={}, headers={CSRF_HEADER: csrf_token}
    )
    assert forbidden_conversation.status_code == 403
    assert forbidden_conversation.json() == {"detail": "forbidden_role"}

    # A customer session, conversely, can never reach /staff/me.
    customer_account = it_accounts["CLI-TFMULTI00001"]
    customer_login_response = app_client.post(
        "/api/v1/auth/login",
        json={
            "document_type": customer_account.document_type,
            "document_number": customer_account.document_number,
            "password": customer_account.password,
        },
    )
    assert customer_login_response.status_code == 200

    forbidden_staff_me = app_client.get("/api/v1/staff/me")
    assert forbidden_staff_me.status_code == 403
    assert forbidden_staff_me.json() == {"detail": "forbidden_role"}

    # Customer credentials never authenticate against staff login (D3): the
    # username here doesn't even match a customer's document, so this also
    # proves an unknown username collapses into the same message.
    wrong_role_login = app_client.post(
        "/api/v1/auth/staff/login",
        json={"username": it_staff_account.username, "password": customer_account.password},
    )
    assert wrong_role_login.status_code == 401
    assert wrong_role_login.json() == {"detail": "invalid_credentials"}
