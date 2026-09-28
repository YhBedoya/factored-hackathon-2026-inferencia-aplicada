"""`POST /auth/login` and `GET /auth/me` integration test (D2, D6, D7, D9),
and `POST /auth/otp/verify` (D3-A4 D4, D5).

Runs against the real dev Postgres and Redis through `app_client` (D19): the
one place this card proves a request never gets back a raw document number,
a normalized one, a last name or another customer's `customer_id`, and the
one place D7's rate limit is proven end to end against a real Redis (the
key shape itself is `test_login_pii.py`'s job, with a fake).

`test_otp_verify` doesn't rely on the conftest Redis cleanup patterns for
`rl:otp:*` (T2's job elsewhere in this card): `it_accounts` mints a fresh
`account_id` per test run, so this run's `rl:otp:<account_id>` key can never
collide with a previous run's leftovers.

See `docs/specs/d2-a-login-read-tools-api.md` "Contracts" -> "HTTP", D2, D6,
D7, D9 and `docs/specs/d3-a-guardrails-write-path.md` "Contracts" -> "HTTP",
D4, D5.
"""

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.domains.identity.tokens import CSRF_HEADER, decode_token
from app.main import create_app
from tests.integration.conftest import ItAccount


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
