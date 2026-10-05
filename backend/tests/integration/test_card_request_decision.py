"""D9-C staff decision over the HTTP API (spec tests T11, T12, T14; R2, R13).

A conversation is opened through the API as `CLI-TFMULTI00001`, a pending open
credit request is created through `cards.service`, and a `creditos` handoff
whose packet carries the request is claimed by `it.creditos`. Rows the tests
add to the shared throwaway database are removed afterwards so other tests see
the fixture customers as they were.
"""

import asyncio
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.rows import dict_row

from app.core.db import get_engine
from app.core.redis import get_redis
from app.domains.cards import service as cards_service
from app.domains.handoff import repository as handoff_repository
from app.domains.handoff.schemas import CardRequestBlock, HandoffPacket
from tests.integration.conftest import ItAccount, ItStaff
from tests.integration.test_staff_round_trip import (
    Headers,
    _customer_login,
    _open_conversation,
    _psycopg_dsn,
    _staff_login,
)

_CUSTOMER_ID = "CLI-TFMULTI00001"


@dataclass
class _Case:
    dsn: str
    conversation_id: str
    handoff_id: str
    request_id: uuid.UUID
    creditos: Headers
    retencion: Headers
    client: TestClient

    def decide(self, headers: Headers, body: dict[str, str], key: str | None = None) -> Any:
        return self.client.post(
            f"/api/v1/staff/handoffs/{self.handoff_id}/card-request/decision",
            json=body,
            headers={**headers, "Idempotency-Key": key or str(uuid.uuid4())},
        )

    def rows(self, sql: str, *params: Any) -> list[dict[str, Any]]:
        with psycopg.connect(self.dsn, row_factory=dict_row) as conn:
            return conn.execute(sql, params).fetchall()

    def new_products(self) -> int:
        rows = self.rows(
            "SELECT count(*) AS n FROM bank.products WHERE customer_id = %s AND origin = 'app'",
            _CUSTOMER_ID,
        )
        return int(rows[0]["n"])

    def request_status(self) -> str:
        return str(
            self.rows("SELECT status FROM app.card_requests WHERE id = %s", self.request_id)[0][
                "status"
            ]
        )


async def _seed(conversation_id: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID]:
    request = await cards_service.create_open_request(
        _CUSTOMER_ID, conversation_id, "credit", {}, idempotency_key=str(uuid.uuid4())
    )
    handoff_id = uuid.uuid4()
    packet = HandoffPacket(
        handoff_id=handoff_id,
        conversation_id=conversation_id,
        queue="creditos",
        priority="normal",
        reason="card_open_request",
        language="es",
        request="Solicitud de tarjeta de credito.",
        verified_facts=[],
        actions_taken=[],
        evidence=[],
        open_questions=[],
        escalation_rules_hit=[],
        policy_version="it-policy",
        created_at=datetime.now(UTC),
        card_request=CardRequestBlock(
            request_id=request.id,
            reference=request.reference,
            kind="open",
            card_kind="credit",
            card_mask=None,
            reason_code=None,
        ),
    )
    await handoff_repository.insert_handoff(packet, "normal")
    return request.id, handoff_id


@pytest.fixture
def case(
    app_client: TestClient,
    it_accounts: dict[str, ItAccount],
    it_staff: dict[str, ItStaff],
    it_db: str,
) -> Iterator[_Case]:
    dsn = _psycopg_dsn(it_db)
    customer = _customer_login(app_client, it_accounts[_CUSTOMER_ID])
    conversation_id = _open_conversation(app_client, customer)
    # The API call above bound the cached engine/Redis to the portal loop: seed on a
    # fresh one, then drop it again so the app rebuilds its own (see `it_accounts`).
    get_engine.cache_clear()
    get_redis.cache_clear()
    request_id, handoff_id = asyncio.run(_seed(uuid.UUID(conversation_id)))
    get_engine.cache_clear()
    get_redis.cache_clear()
    creditos = _staff_login(app_client, it_staff["creditos"])
    retencion = _staff_login(app_client, it_staff["retencion"])
    claim = app_client.post(f"/api/v1/staff/handoffs/{handoff_id}/claim", headers=creditos)
    assert claim.status_code == 200, claim.text
    yield _Case(dsn, conversation_id, str(handoff_id), request_id, creditos, retencion, app_client)
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(
            "DELETE FROM bank.products WHERE origin = 'app' AND customer_id = %s", (_CUSTOMER_ID,)
        )
        conn.execute("DELETE FROM app.card_requests WHERE customer_id = %s", (_CUSTOMER_ID,))
        conn.execute("DELETE FROM app.handoffs WHERE id = %s", (uuid.UUID(str(handoff_id)),))


_CLOSE_PRODUCT = "PRD-TFM1CRED0001"  # balance 1234.50 in the fixture


async def _seed_close(conversation_id: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID]:
    request = await cards_service.create_close_request(
        _CUSTOMER_ID,
        conversation_id,
        _CLOSE_PRODUCT,
        "no_longer_needed",
        idempotency_key=str(uuid.uuid4()),
    )
    handoff_id = uuid.uuid4()
    packet = HandoffPacket(
        handoff_id=handoff_id,
        conversation_id=conversation_id,
        queue="retencion",
        priority="normal",
        reason="card_close_request",
        language="es",
        request="Solicitud de cierre de tarjeta.",
        verified_facts=[],
        actions_taken=[],
        evidence=[],
        open_questions=[],
        escalation_rules_hit=[],
        policy_version="it-policy",
        created_at=datetime.now(UTC),
        card_request=CardRequestBlock(
            request_id=request.id,
            reference=request.reference,
            kind="close",
            card_kind="credit",
            card_mask=None,
            reason_code="no_longer_needed",
        ),
    )
    await handoff_repository.insert_handoff(packet, "normal")
    return request.id, handoff_id


@pytest.fixture
def close_case(
    app_client: TestClient,
    it_accounts: dict[str, ItAccount],
    it_staff: dict[str, ItStaff],
    it_db: str,
) -> Iterator[_Case]:
    dsn = _psycopg_dsn(it_db)
    customer = _customer_login(app_client, it_accounts[_CUSTOMER_ID])
    conversation_id = _open_conversation(app_client, customer)
    get_engine.cache_clear()
    get_redis.cache_clear()
    request_id, handoff_id = asyncio.run(_seed_close(uuid.UUID(conversation_id)))
    get_engine.cache_clear()
    get_redis.cache_clear()
    creditos = _staff_login(app_client, it_staff["creditos"])
    retencion = _staff_login(app_client, it_staff["retencion"])
    claim = app_client.post(f"/api/v1/staff/handoffs/{handoff_id}/claim", headers=retencion)
    assert claim.status_code == 200, claim.text
    yield _Case(dsn, conversation_id, str(handoff_id), request_id, creditos, retencion, app_client)
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute("DELETE FROM app.card_requests WHERE customer_id = %s", (_CUSTOMER_ID,))
        conn.execute("DELETE FROM app.handoffs WHERE id = %s", (uuid.UUID(str(handoff_id)),))


def test_cancel_nonzero_balance_writes_nothing(close_case: _Case) -> None:
    case = close_case

    def snapshot() -> tuple[Any, ...]:
        product = case.rows(
            "SELECT product_status, current_balance FROM bank.products WHERE product_id = %s",
            _CLOSE_PRODUCT,
        )
        history = case.rows(
            "SELECT count(*) AS n FROM app.card_status_history WHERE product_id = %s",
            _CLOSE_PRODUCT,
        )
        request = case.rows("SELECT * FROM app.card_requests WHERE id = %s", case.request_id)
        audit = case.rows(
            "SELECT count(*) AS n FROM audit.audit_events WHERE conversation_id = %s "
            "AND payload->>'tool' = 'cards.decide_card_request'",
            uuid.UUID(case.conversation_id),
        )
        return product, history, request, audit

    before = snapshot()
    refused = case.decide(case.retencion, {"decision": "cancel"})

    assert refused.status_code == 409, refused.text
    assert refused.json()["detail"] == "balance_not_zero"
    assert snapshot() == before
    assert before[0][0]["product_status"] == "Active"


def test_decision_non_claimant_refused(case: _Case) -> None:
    refused = case.decide(case.retencion, {"decision": "decline", "decline_reason": "other"})
    assert refused.status_code == 409
    assert refused.json()["detail"] == "not_claimant"
    assert case.new_products() == 0
    assert case.request_status() == "pending"

    returned = case.client.post(
        f"/api/v1/staff/handoffs/{case.handoff_id}/return", headers=case.creditos
    )
    assert returned.status_code == 409
    assert returned.json()["detail"] == "request_undecided"


def test_decision_limit_out_of_bounds(case: _Case) -> None:
    response = case.decide(case.creditos, {"decision": "approve", "credit_limit": "999"})
    assert response.status_code == 422
    assert response.json()["detail"] == "limit_out_of_bounds"
    assert case.new_products() == 0
    assert case.request_status() == "pending"


def test_decision_idempotency_key_writes_once(case: _Case) -> None:
    panel = case.client.get(
        f"/api/v1/staff/handoffs/{case.handoff_id}/card-request", headers=case.creditos
    )
    assert panel.status_code == 200, panel.text
    body = {"decision": "approve", "credit_limit": panel.json()["credit_bounds"]["min"]}
    key = str(uuid.uuid4())

    first = case.decide(case.creditos, body, key)
    second = case.decide(case.creditos, body, key)

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert case.new_products() == 1
    assert first.json()["verified"] is True
    assert second.json()["verified"] == first.json()["verified"]
    assert second.json()["request"] == first.json()["request"]
    assert first.json()["message_id"] is not None
    assert second.json()["message_id"] is None
    tool_calls = case.rows(
        "SELECT count(*) AS n FROM audit.audit_events WHERE conversation_id = %s "
        "AND type = 'tool_call' AND payload->>'tool' = 'cards.decide_card_request'",
        uuid.UUID(case.conversation_id),
    )
    assert tool_calls[0]["n"] == 1


def test_cancel_zero_balance_closes_card_and_replays(close_case: _Case) -> None:
    case = close_case
    with psycopg.connect(case.dsn, autocommit=True) as conn:
        conn.execute(
            "UPDATE bank.products SET current_balance = 0 WHERE product_id = %s", (_CLOSE_PRODUCT,)
        )
    key = str(uuid.uuid4())
    try:
        first = case.decide(case.retencion, {"decision": "cancel"}, key)
        second = case.decide(case.retencion, {"decision": "cancel"}, key)

        assert first.status_code == 200, first.text
        assert first.json()["verified"] is True
        assert first.json()["request"]["decision"] == "cancel"
        assert first.json()["message_id"] is not None
        status = case.rows(
            "SELECT product_status FROM bank.products WHERE product_id = %s", _CLOSE_PRODUCT
        )
        assert status[0]["product_status"] == "Closed"
        history = case.rows(
            "SELECT new_status FROM app.card_status_history WHERE idempotency_key = %s", key
        )
        assert [h["new_status"] for h in history] == ["Closed"]
        audit = case.rows(
            "SELECT type FROM audit.audit_events WHERE conversation_id = %s "
            "AND payload->>'tool' = 'cards.decide_card_request' AND type IN "
            "('tool_call','readback','tool_result')",
            uuid.UUID(case.conversation_id),
        )
        assert sorted(a["type"] for a in audit) == ["readback", "tool_call", "tool_result"]

        assert second.status_code == 200, second.text
        assert second.json()["verified"] is True
        assert second.json()["message_id"] is None
        assert (
            case.rows(
                "SELECT count(*) AS n FROM app.card_status_history WHERE idempotency_key = %s", key
            )[0]["n"]
            == 1
        )
    finally:
        with psycopg.connect(case.dsn, autocommit=True) as conn:
            conn.execute("DELETE FROM app.card_status_history WHERE idempotency_key = %s", (key,))
            conn.execute(
                "UPDATE bank.products SET current_balance = 1234.50, product_status = 'Active' "
                "WHERE product_id = %s",
                (_CLOSE_PRODUCT,),
            )
