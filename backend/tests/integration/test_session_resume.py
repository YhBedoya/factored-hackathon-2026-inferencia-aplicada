"""D12 / R13: a session that expires while a confirmation is pending changes
nothing. `/confirmations` and `/messages` answer `401 session_expired`
without touching the checkpoint's `pending`, the Redis plan, the turn lock,
`app.messages` or `audit.audit_events`; another customer gets `404`; and the
owner, logged in again, resumes by re-sending the same request.

Redis and checkpoint reads run on `app_client`'s own portal loop
(`get_redis()`/the checkpointer pool are loop-bound), so nothing here clears
the caches while the app is running.

See `docs/specs/d6-a-reliability-resume-injection-dq.md` D12, D13.
"""

import re
import uuid
from typing import Any

import psycopg
from fastapi.testclient import TestClient
from psycopg.rows import dict_row

from app.core.redis import get_redis
from app.domains.conversation.runner import checkpointed_confirmation_token
from app.domains.conversation.schemas import NLUResult, NLUSlots
from app.domains.identity.tokens import CSRF_HEADER
from app.domains.policy.confirmation_redis import RedisConfirmationStore
from tests.conftest import ScriptedLLM
from tests.integration.conftest import ItAccount
from tests.integration.test_write_path_api import (
    _confirm_token,
    _login,
    _psycopg_dsn,
    _wait_for_bot_message,
)

_A_ID = "CLI-TFSINGLE0002"
_A_CARD_ID = "PRD-TFS2CRED0001"  # credit, last4 2222
_B_ID = "CLI-TFMULTI00001"


def _counts(dsn: str, conversation_id: str) -> tuple[int, int]:
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        messages = conn.execute(
            "SELECT count(*) AS n FROM app.messages WHERE conversation_id = %s",
            (uuid.UUID(conversation_id),),
        ).fetchone()
        events = conn.execute(
            "SELECT count(*) AS n FROM audit.audit_events WHERE conversation_id = %s",
            (uuid.UUID(conversation_id),),
        ).fetchone()
    assert messages is not None
    assert events is not None
    return messages["n"], events["n"]


def _snapshot(client: TestClient, dsn: str, conversation_id: str, token: str) -> dict[str, Any]:
    async def _read() -> dict[str, Any]:
        host = client.app.state.turn_host  # type: ignore[attr-defined]
        return {
            "checkpoint_token": await checkpointed_confirmation_token(
                host, uuid.UUID(conversation_id)
            ),
            "is_open": await RedisConfirmationStore(_A_ID, conversation_id).is_open(token),
            "turn_lock": await get_redis().exists(f"turn:{conversation_id}"),
        }

    assert client.portal is not None
    state: dict[str, Any] = client.portal.call(_read)
    state["messages"], state["audit_events"] = _counts(dsn, conversation_id)
    return state


def test_expired_session_keeps_pending_and_only_owner_resumes(
    app_client: TestClient,
    it_accounts: dict[str, ItAccount],
    it_db: str,
    restore_cards: set[str],
) -> None:
    dsn = _psycopg_dsn(it_db)
    restore_cards.add(_A_CARD_ID)
    app_client.app.state.turn_host.llm = ScriptedLLM(  # type: ignore[attr-defined]
        {
            "nlu": [
                NLUResult(
                    language="es",
                    intents=["card_block"],
                    status="clear",
                    slots=NLUSlots(card_hint="credit", block_kind="permanent_block"),
                )
            ]
        }
    )

    account_a = it_accounts[_A_ID]
    csrf_a = _login(app_client, account_a)
    create = app_client.post("/api/v1/conversations", json={}, headers={CSRF_HEADER: csrf_a})
    assert create.status_code == 201
    conversation_id = create.json()["conversation_id"]
    base_url = f"/api/v1/conversations/{conversation_id}"

    ask_response = app_client.post(
        f"{base_url}/messages", json={"text": "bloquea mi tarjeta"}, headers={CSRF_HEADER: csrf_a}
    )
    assert ask_response.status_code == 202
    ask = _wait_for_bot_message(dsn, ask_response.json()["turn_id"])
    token = _confirm_token(ask["ui_payload"])

    before = _snapshot(app_client, dsn, conversation_id, token)
    assert before["checkpoint_token"] == token
    assert before["is_open"] is True
    assert before["turn_lock"] == 0

    # --- Expire A's session: revoke the jti, then present the old cookie. ---
    old_session = app_client.cookies["session"]
    old_csrf = app_client.cookies["csrf_token"]
    assert app_client.post("/api/v1/auth/logout", headers={CSRF_HEADER: csrf_a}).status_code == 204
    app_client.cookies.clear()
    app_client.cookies.set("session", old_session)
    app_client.cookies.set("csrf_token", old_csrf)

    confirm_body = {"decision": "confirm"}
    for path, body in (
        (f"{base_url}/confirmations/{token}", confirm_body),
        (f"{base_url}/messages", {"text": "hola"}),
    ):
        response = app_client.post(path, json=body, headers={CSRF_HEADER: old_csrf})
        assert response.status_code == 401
        assert response.json() == {"detail": "session_expired"}
    assert _snapshot(app_client, dsn, conversation_id, token) == before

    # --- Another customer: 404 on both routes, A's plan stays open (R13). ---
    app_client.cookies.clear()
    csrf_b = _login(app_client, it_accounts[_B_ID])
    for path, body in (
        (f"{base_url}/confirmations/{token}", confirm_body),
        (f"{base_url}/messages", {"text": "hola"}),
    ):
        response = app_client.post(path, json=body, headers={CSRF_HEADER: csrf_b})
        assert response.status_code == 404
    assert _snapshot(app_client, dsn, conversation_id, token) == before

    # --- A logs in again and re-sends the same confirmation. ---
    app_client.cookies.clear()
    csrf_a = _login(app_client, account_a)
    resume = app_client.post(
        f"{base_url}/confirmations/{token}", json=confirm_body, headers={CSRF_HEADER: csrf_a}
    )
    assert resume.status_code == 202
    done = _wait_for_bot_message(dsn, resume.json()["turn_id"])
    # R3: the "done" text only comes from a verified read-back.
    assert "bloqueada de forma permanente" in done["content"]
    assert re.search(r"2222", done["content"])

    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        status_row = conn.execute(
            "SELECT product_status FROM bank.products WHERE product_id = %s", (_A_CARD_ID,)
        ).fetchone()
    assert status_row is not None
    assert status_row["product_status"] == "Blocked"
