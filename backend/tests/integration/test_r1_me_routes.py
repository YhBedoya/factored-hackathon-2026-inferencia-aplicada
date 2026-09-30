"""R1 integration test for `/api/v1/me/*`: customer B gets the exact same
`404 not_found` for customer A's card (on the detail route and as a
`/me/transactions?card_id=` filter) as for a card id nobody owns, and B's
card and transaction lists contain none of A's ids.

Customer A (`CLI-TFMULTI00001`) does read her own data first, so the "none of
A's ids" assertions below can't pass vacuously.

See `docs/specs/landing-home-bienvenida.md` "Test list".
"""

from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.db import get_engine
from app.core.redis import get_redis
from app.main import create_app
from tests.integration.conftest import ItAccount

_NOT_FOUND_BODY = {"detail": "not_found"}
_A_CARD = "PRD-TFM1CRED0001"


def _login(client: TestClient, account: ItAccount) -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={
            "document_type": account.document_type,
            "document_number": account.document_number,
            "password": account.password,
        },
    )
    assert response.status_code == 200


def test_other_customer_cannot_read(
    app_client: TestClient, it_accounts: dict[str, ItAccount]
) -> None:
    _login(app_client, it_accounts["CLI-TFMULTI00001"])
    a_cards = app_client.get("/api/v1/me/cards")
    assert a_cards.status_code == 200
    a_card_ids = {card["card_id"] for card in a_cards.json()}
    assert _A_CARD in a_card_ids
    assert app_client.get(f"/api/v1/me/cards/{_A_CARD}").status_code == 200
    a_page = app_client.get("/api/v1/me/transactions")
    assert a_page.status_code == 200
    a_tx_ids = {row["tx_id"] for row in a_page.json()["items"]}
    assert a_tx_ids
    assert app_client.get("/api/v1/me/transactions?cursor=not-a-cursor").status_code == 422

    # Same loop-bound cache reset `test_r13_ownership.py` does before a
    # second `TestClient`.
    get_settings.cache_clear()
    get_engine.cache_clear()
    get_redis.cache_clear()

    with TestClient(create_app()) as client_b:
        _login(client_b, it_accounts["CLI-TFSINGLE0002"])

        for card_id in (_A_CARD, "PRD-DOES-NOT-EXIST"):
            detail = client_b.get(f"/api/v1/me/cards/{card_id}")
            assert detail.status_code == 404
            assert detail.json() == _NOT_FOUND_BODY
            filtered = client_b.get(f"/api/v1/me/transactions?card_id={card_id}")
            assert filtered.status_code == 404
            assert filtered.json() == _NOT_FOUND_BODY

        b_cards = client_b.get("/api/v1/me/cards")
        assert b_cards.status_code == 200
        assert not a_card_ids & {card["card_id"] for card in b_cards.json()}
        b_page = client_b.get("/api/v1/me/transactions")
        assert b_page.status_code == 200
        assert not a_tx_ids & {row["tx_id"] for row in b_page.json()["items"]}
