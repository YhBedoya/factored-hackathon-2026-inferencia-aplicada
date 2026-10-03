"""R13 ownership integration test: `get_owned_conversation` gives the exact
same `404 not_found` whether a conversation is missing or belongs to another
customer (D18).

Customer A (`CLI-TFMULTI00001`) creates a conversation. Customer B
(`CLI-TFSINGLE0002`), logged in on a separate client with her own CSRF
token, gets `404` posting a message, opening the stream or posting a
confirmation on A's conversation id -- and so does a random UUID nobody
owns. `get_owned_conversation` runs as a route dependency, before any route
body does anything, so no turn is ever scheduled and no LLM is ever called.

See `docs/specs/d2-a-login-read-tools-api.md` "Contracts" -> the three
`/conversations` rows, D18; `docs/specs/d3-a-guardrails-write-path.md` D7;
`docs/solution-docs/04-contracts.md` §3 "Auth (ADR-025)".
"""

from uuid import uuid4

from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.db import get_engine
from app.core.redis import get_redis
from app.domains.identity.tokens import CSRF_HEADER
from app.main import create_app
from tests.integration.conftest import ItAccount

_NOT_FOUND_BODY = {"detail": "not_found"}


def _login(client: TestClient, account: ItAccount) -> str:
    response = client.post(
        "/api/v1/auth/login",
        json={
            "document_type": account.document_type,
            "document_number": account.document_number,
            "password": account.password,
        },
    )
    assert response.status_code == 200
    return response.cookies["csrf_token"]


def test_other_customer_conversation_is_404(
    app_client: TestClient, it_accounts: dict[str, ItAccount]
) -> None:
    account_a = it_accounts["CLI-TFMULTI00001"]
    account_b = it_accounts["CLI-TFSINGLE0002"]

    csrf_a = _login(app_client, account_a)
    create_response = app_client.post(
        "/api/v1/conversations", json={}, headers={CSRF_HEADER: csrf_a}
    )
    assert create_response.status_code == 201
    conversation_id = create_response.json()["conversation_id"]

    # `get_settings`/`get_engine`/`get_redis` are `lru_cache`d and bound to
    # their event loop (state file conventions): `app_client`'s `TestClient`
    # runs its own portal loop, and a second `TestClient` below runs another
    # one -- clear the caches so client_b's requests build their own clients
    # instead of reusing app_client's loop-bound ones.
    get_settings.cache_clear()
    get_engine.cache_clear()
    get_redis.cache_clear()

    with TestClient(create_app()) as client_b:
        csrf_b = _login(client_b, account_b)

        message_response = client_b.post(
            f"/api/v1/conversations/{conversation_id}/messages",
            json={"text": "hola"},
            headers={CSRF_HEADER: csrf_b},
        )
        assert message_response.status_code == 404
        assert message_response.json() == _NOT_FOUND_BODY

        stream_response = client_b.get(f"/api/v1/conversations/{conversation_id}/stream")
        assert stream_response.status_code == 404
        assert stream_response.json() == _NOT_FOUND_BODY

        random_id = str(uuid4())
        random_message_response = client_b.post(
            f"/api/v1/conversations/{random_id}/messages",
            json={"text": "hola"},
            headers={CSRF_HEADER: csrf_b},
        )
        assert random_message_response.status_code == 404
        assert random_message_response.json() == _NOT_FOUND_BODY

        random_stream_response = client_b.get(f"/api/v1/conversations/{random_id}/stream")
        assert random_stream_response.status_code == 404
        assert random_stream_response.json() == _NOT_FOUND_BODY

        # D7: `get_owned_conversation` runs before the confirmation-token
        # checks, so a foreign conversation id is still 404, not 409 -- the
        # token itself is never even looked at.
        confirmation_response = client_b.post(
            f"/api/v1/conversations/{conversation_id}/confirmations/any-token",
            json={"decision": "confirm"},
            headers={CSRF_HEADER: csrf_b},
        )
        assert confirmation_response.status_code == 404
        assert confirmation_response.json() == _NOT_FOUND_BODY
