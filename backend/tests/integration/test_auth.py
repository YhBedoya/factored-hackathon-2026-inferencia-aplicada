"""`POST /auth/login` and `GET /auth/me` integration test (D2, D6, D7, D9).

Runs against the real dev Postgres and Redis through `app_client` (D19): the
one place this card proves a request never gets back a raw document number,
a normalized one, a last name or another customer's `customer_id`, and the
one place D7's rate limit is proven end to end against a real Redis (the
key shape itself is `test_login_pii.py`'s job, with a fake).

See `docs/specs/d2-a-login-read-tools-api.md` "Contracts" -> "HTTP", D2, D6, D7, D9.
"""

from fastapi.testclient import TestClient

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
