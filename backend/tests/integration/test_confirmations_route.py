"""D7 "Done when": a replayed, foreign-owner or merely-issued-but-not-
checkpointed token on `POST /confirmations/{token_id}` is `409
confirmation_invalid` before any turn is scheduled (R2) -- no `turn:
<conversation_id>` lock ever appears and no `app.messages` row is persisted
for the conversation. `POST /messages` rejects neither/both of
`text`/`resume` with `422` (D6).

`RedisConfirmationStore` and `store.list_messages` are driven directly, off
`app_client`'s own conversation, in their own `asyncio.run()` calls -- not
through the graph -- so case (iii)'s plan is genuinely open but nothing is
checkpointed waiting on it. `_redis_run` clears the loop-bound
`get_redis`/`get_engine` caches before and after each such call (state file
conventions): `app_client`'s `TestClient` runs its own portal loop for the
whole test, so a client any bare `asyncio.run()` built on its own, now-closed
loop must never survive to be reused by that portal or by the next
`asyncio.run()`.

See `docs/specs/d3-a-guardrails-write-path.md` D6, D7; §"Test list" ->
`integration/test_confirmations_route.py::test_replayed_token_is_409`.
"""

import asyncio
from collections.abc import Coroutine
from typing import Any
from uuid import UUID

from fastapi.testclient import TestClient

from app.core.db import get_engine
from app.core.redis import get_redis
from app.domains.conversation import store
from app.domains.identity.tokens import CSRF_HEADER
from app.domains.policy.confirmation import PlanStep
from app.domains.policy.confirmation_redis import RedisConfirmationStore
from tests.integration.conftest import ItAccount

_CUSTOMER_A = "CLI-TFMULTI00001"
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
