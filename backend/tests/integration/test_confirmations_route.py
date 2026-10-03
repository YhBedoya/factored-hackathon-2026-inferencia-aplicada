"""D7 "Done when": a replayed, foreign-owner or merely-issued-but-not-
checkpointed token on `POST /confirmations/{token_id}` is `409
confirmation_invalid` before any turn is scheduled (R2) -- no `turn:
<conversation_id>` lock ever appears and no `app.messages` row is persisted
for the conversation. `POST /messages` rejects neither/both of
`text`/`resume` with `422` (D6). D4-B D7 adds the pick's own gate: a
`selection` body is `409 selection_invalid` whenever no transaction list is
checkpointed as pending, or an id in it wasn't actually offered (R1) --
`test_injected_tx_id_is_409`, below.

`RedisConfirmationStore` and `store.list_messages` are driven directly, off
`app_client`'s own conversation, in their own `asyncio.run()` calls -- not
through the graph -- so case (iii)'s plan is genuinely open but nothing is
checkpointed waiting on it. `_redis_run` clears the loop-bound
`get_redis`/`get_engine` caches before and after each such call (state file
conventions): `app_client`'s `TestClient` runs its own portal loop for the
whole test, so a client any bare `asyncio.run()` built on its own, now-closed
loop must never survive to be reused by that portal or by the next
`asyncio.run()`. `test_injected_tx_id_is_409`'s second case needs a real
turn to actually run first (to checkpoint a pending transaction list), so it
polls `app.messages` with a fresh sync `psycopg` connection instead
(`test_write_path_api.py`'s own harness note and pattern).

See `docs/specs/d3-a-guardrails-write-path.md` D6, D7; `docs/specs/
d4-b-disputes-handoff-screens.md` D7; §"Test list" ->
`integration/test_confirmations_route.py::test_replayed_token_is_409`,
`::test_injected_tx_id_is_409`.
"""

import asyncio
import time
from collections.abc import Coroutine
from typing import Any
from uuid import UUID

import psycopg
from fastapi.testclient import TestClient
from psycopg.rows import dict_row

from app.core.db import get_engine
from app.core.redis import get_redis
from app.domains.conversation import store
from app.domains.conversation.schemas import NLUResult
from app.domains.identity.tokens import CSRF_HEADER
from app.domains.policy.confirmation import PlanStep
from app.domains.policy.confirmation_redis import RedisConfirmationStore
from tests.conftest import ScriptedLLM
from tests.integration.conftest import ItAccount

_CUSTOMER_A = "CLI-TFMULTI00001"
_SINGLE_CUSTOMER_ID = "CLI-TFSINGLE0002"
# CLI-TFMULTI00001's own transaction: never offered to _SINGLE_CUSTOMER_ID's pick (R1).
_FOREIGN_TX_ID = "TRX-TFM1CRED0001TXN01"
_FAKE_TX_ID = "TRX-DOES-NOT-EXIST"
_FOREIGN_CONVERSATION_ID = "11111111-1111-1111-1111-111111111111"
_TOOL = "cards.lock_card"
_ARGS = {"card_id": "PRD-1"}


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


def _redis_run[T](coro: Coroutine[Any, Any, T]) -> T:
    get_redis.cache_clear()
    get_engine.cache_clear()
    try:
        return asyncio.run(coro)
    finally:
        get_redis.cache_clear()
        get_engine.cache_clear()


async def _assert_no_turn_scheduled(conversation_id: str) -> None:
    assert await get_redis().exists(f"turn:{conversation_id}") == 0
    assert await store.list_messages(UUID(conversation_id)) == []


def test_replayed_token_is_409(app_client: TestClient, it_accounts: dict[str, ItAccount]) -> None:
    account_a = it_accounts[_CUSTOMER_A]
    csrf_a = _login(app_client, account_a)

    create_response = app_client.post(
        "/api/v1/conversations", json={}, headers={CSRF_HEADER: csrf_a}
    )
    assert create_response.status_code == 201
    conversation_id = create_response.json()["conversation_id"]

    # (i) A fully consumed single-step plan, replayed.
    async def _issue_and_consume() -> str:
        confirmation_store = RedisConfirmationStore(_CUSTOMER_A, conversation_id)
        plan = await confirmation_store.issue([PlanStep(tool=_TOOL, args=_ARGS)])
        await confirmation_store.consume_step(plan.token_id, _TOOL, _ARGS)
        return plan.token_id

    consumed_token = _redis_run(_issue_and_consume())
    response = app_client.post(
        f"/api/v1/conversations/{conversation_id}/confirmations/{consumed_token}",
        json={"decision": "confirm"},
        headers={CSRF_HEADER: csrf_a},
    )
    assert response.status_code == 409
    assert response.json() == {"detail": "confirmation_invalid"}
    _redis_run(_assert_no_turn_scheduled(conversation_id))

    # (ii) Issued for A, but on a different conversation.
    async def _issue_foreign_conversation() -> str:
        confirmation_store = RedisConfirmationStore(_CUSTOMER_A, _FOREIGN_CONVERSATION_ID)
        plan = await confirmation_store.issue([PlanStep(tool=_TOOL, args=_ARGS)])
        return plan.token_id

    foreign_token = _redis_run(_issue_foreign_conversation())
    response = app_client.post(
        f"/api/v1/conversations/{conversation_id}/confirmations/{foreign_token}",
        json={"decision": "confirm"},
        headers={CSRF_HEADER: csrf_a},
    )
    assert response.status_code == 409
    assert response.json() == {"detail": "confirmation_invalid"}
    _redis_run(_assert_no_turn_scheduled(conversation_id))

    # (iii) Issued for A, on this very conversation -- open, but no turn has
    # ever run here, so nothing is checkpointed waiting on it.
    async def _issue_not_checkpointed() -> str:
        confirmation_store = RedisConfirmationStore(_CUSTOMER_A, conversation_id)
        plan = await confirmation_store.issue([PlanStep(tool=_TOOL, args=_ARGS)])
        return plan.token_id

    open_token = _redis_run(_issue_not_checkpointed())
    response = app_client.post(
        f"/api/v1/conversations/{conversation_id}/confirmations/{open_token}",
        json={"decision": "confirm"},
        headers={CSRF_HEADER: csrf_a},
    )
    assert response.status_code == 409
    assert response.json() == {"detail": "confirmation_invalid"}
    _redis_run(_assert_no_turn_scheduled(conversation_id))

    neither_response = app_client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={},
        headers={CSRF_HEADER: csrf_a},
    )
    assert neither_response.status_code == 422

    both_response = app_client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"text": "x", "resume": "step_up"},
        headers={CSRF_HEADER: csrf_a},
    )
    assert both_response.status_code == 422


def _psycopg_dsn(database_url: str) -> str:
    """`it_db`'s asyncpg URL -> a plain psycopg3 DSN (same conversion as
    `tests/integration/conftest.py`'s own private `_psycopg_dsn`, and
    `test_write_path_api.py`'s copy)."""
    return database_url.replace("postgresql+asyncpg://", "postgresql://")


def _wait_for_bot_message(dsn: str, turn_id: str, *, timeout: float = 20.0) -> dict[str, Any]:
    """Poll `app.messages` for `turn_id`'s bot reply with a fresh sync
    connection each try (`test_write_path_api.py`'s harness note and
    pattern): this harness never touches the loop-bound `get_engine()`
    `app_client`'s own portal loop needs to read a turn's own result.
    Returns `{content, ui_payload}`.
    """
    deadline = time.monotonic() + timeout
    while True:
        with psycopg.connect(dsn, row_factory=dict_row) as conn:
            row = conn.execute(
                "SELECT content_masked AS content, ui_payload FROM app.messages"
                " WHERE turn_id = %s AND role = 'bot'",
                (UUID(turn_id),),
            ).fetchone()
        if row is not None:
            return row
        if time.monotonic() > deadline:
            raise AssertionError(f"no bot message for turn {turn_id} within {timeout}s")
        time.sleep(0.1)


def _message_count(dsn: str, conversation_id: str) -> int:
    """A sync count, not `store.list_messages` (whose `MessageRow.ui_payload`
    only accepts a JSON object): a real `unrecognized_charge` turn's bot row
    carries a *list* of `UIEvent`s (`transaction_list`, same as every other
    flow's `confirm`), which that schema can't parse. Same avoidance
    `test_write_path_api.py` already makes for message content, for the
    same reason."""
    with psycopg.connect(dsn) as conn:
        row = conn.execute(
            "SELECT count(*) FROM app.messages WHERE conversation_id = %s",
            (UUID(conversation_id),),
        ).fetchone()
    assert row is not None
    return row[0]


async def _assert_no_turn_lock(conversation_id: str) -> None:
    assert await get_redis().exists(f"turn:{conversation_id}") == 0


def test_injected_tx_id_is_409(
    app_client: TestClient, it_accounts: dict[str, ItAccount], it_db: str
) -> None:
    """D4-B D7, human Q6: a `selection` is `409 selection_invalid` -- no
    turn scheduled -- both when no transaction list is checkpointed as
    pending at all, and when it is, but the picked id was never offered to
    this customer (R1's injection guard)."""
    dsn = _psycopg_dsn(it_db)

    # (i) No list pending: a selection on a brand-new conversation.
    account_a = it_accounts[_CUSTOMER_A]
    csrf_a = _login(app_client, account_a)
    no_list_create = app_client.post(
        "/api/v1/conversations", json={}, headers={CSRF_HEADER: csrf_a}
    )
    assert no_list_create.status_code == 201
    no_list_conversation_id = no_list_create.json()["conversation_id"]

    no_list_response = app_client.post(
        f"/api/v1/conversations/{no_list_conversation_id}/messages",
        json={"selection": {"tx_ids": [_FAKE_TX_ID]}},
        headers={CSRF_HEADER: csrf_a},
    )
    assert no_list_response.status_code == 409
    assert no_list_response.json() == {"detail": "selection_invalid"}
    _redis_run(_assert_no_turn_lock(no_list_conversation_id))
    assert _message_count(dsn, no_list_conversation_id) == 0

    # (ii) A list is pending, but the picked id belongs to a different
    # customer's card -- never in this pick's own `offered_tx_ids`.
    app_client.app.state.turn_host.llm = ScriptedLLM(
        {"nlu": [NLUResult(language="es", intents=["unrecognized_charge"], status="clear")]}
    )
    account_single = it_accounts[_SINGLE_CUSTOMER_ID]
    csrf_single = _login(app_client, account_single)
    create_response = app_client.post(
        "/api/v1/conversations", json={}, headers={CSRF_HEADER: csrf_single}
    )
    assert create_response.status_code == 201
    conversation_id = create_response.json()["conversation_id"]

    pick_ask_response = app_client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"text": "no reconozco estas compras"},
        headers={CSRF_HEADER: csrf_single},
    )
    assert pick_ask_response.status_code == 202
    pick_ask = _wait_for_bot_message(dsn, pick_ask_response.json()["turn_id"])
    assert [event["kind"] for event in pick_ask["ui_payload"]] == ["transaction_list"]

    message_count = _message_count(dsn, conversation_id)

    injected_response = app_client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"selection": {"tx_ids": [_FOREIGN_TX_ID]}},
        headers={CSRF_HEADER: csrf_single},
    )
    assert injected_response.status_code == 409
    assert injected_response.json() == {"detail": "selection_invalid"}
    _redis_run(_assert_no_turn_lock(conversation_id))
    assert _message_count(dsn, conversation_id) == message_count
