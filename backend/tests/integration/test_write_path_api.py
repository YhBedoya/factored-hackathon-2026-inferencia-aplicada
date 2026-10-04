"""A6 "Done when" over the HTTP API: lock, unlock (with OTP step-up), block
and replacement (with a changed-address OTP) all run through
`ConfirmedWriteTools` against Postgres, and a bank-side block still hands
off with no write (D3-A "End-of-day test" steps 3-5, 7).

The turn itself runs as a background `asyncio.Task` on `app_client`'s own
portal loop (`runner.start_turn`), so this harness never touches the
loop-bound `get_engine()`/`get_redis()` (state file conventions) to read a
turn's own result: `_wait_for_bot_message` polls `app.messages` with a
plain sync `psycopg` connection instead, and only `test_bank_blocked_
unlock_handoff`'s Redis check reuses `test_confirmations_route.py`'s
`_redis_run` cache-clear pattern, after the one turn it drives has already
finished (no task still running to race).

Every write goes through the real `POST /confirmations/{token_id}` route
(D7), never a typed "si"/"no": `ConfirmationDecision` is how `card_block`/
`card_unlock`/`replacement`'s own "confirm" pause resolves. Accepting the
replacement offer and declining the on-file address are still typed
affirm/deny turns (`decision()`'s NLU fallback, `flows/actions.py`), since
no plan exists yet for either to attach a button to.

See `docs/specs/d3-a-guardrails-write-path.md` D6, D7, D16, D17; §"Test
list" -> `test_write_path_api.py`; `docs/solution-docs/07-execution-plan.md`
D3 "End-of-day test" (browser) steps 3-5, 7.
"""

import asyncio
import re
import time
import uuid
from collections.abc import Coroutine
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.rows import dict_row

from app.core.config import get_settings
from app.core.db import get_engine
from app.core.redis import get_redis
from app.domains.conversation.nodes.handoff_summary import HandoffSummaryDraft
from app.domains.conversation.schemas import NLUResult, NLUSlots
from app.domains.conversation.templates import get_template
from app.domains.identity.tokens import CSRF_HEADER
from tests.conftest import ScriptedLLM
from tests.integration.conftest import ItAccount

_DEMO_OTP_CODE = "135790"

_MULTI_CUSTOMER_ID = "CLI-TFMULTI00001"
_MULTI_CARD_ID = "PRD-TFM1CRED0001"  # credit, last4 6475 (fixtures README)

_SINGLE_CUSTOMER_ID = "CLI-TFSINGLE0002"
_SINGLE_CARD_ID = "PRD-TFS2CRED0001"  # credit, last4 2222

_BLOCKED_CUSTOMER_ID = "CLI-TFBLOCKD0003"
_BLOCKED_CARD_ID = "PRD-TFB3DEBT0001"  # bank-side Blocked, last4 3333


def _psycopg_dsn(database_url: str) -> str:
    """`it_db`'s asyncpg URL -> a plain psycopg3 DSN (same conversion as
    `tests/integration/conftest.py`'s own private `_psycopg_dsn`)."""
    return database_url.replace("postgresql+asyncpg://", "postgresql://")


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


def _wait_for_bot_message(dsn: str, turn_id: str, *, timeout: float = 20.0) -> dict[str, Any]:
    """Poll `app.messages` for `turn_id`'s bot reply with a fresh sync
    connection each try (harness note above): returns `{content, ui_payload}`."""
    deadline = time.monotonic() + timeout
    while True:
        with psycopg.connect(dsn, row_factory=dict_row) as conn:
            row = conn.execute(
                "SELECT content_masked AS content, ui_payload FROM app.messages"
                " WHERE turn_id = %s AND role = 'bot'",
                (uuid.UUID(turn_id),),
            ).fetchone()
        if row is not None:
            return row
        if time.monotonic() > deadline:
            raise AssertionError(f"no bot message for turn {turn_id} within {timeout}s")
        time.sleep(0.1)


def _confirm_token(ui_payload: list[dict[str, Any]] | None) -> str:
    assert ui_payload is not None
    event = next(event for event in ui_payload if event["kind"] == "confirm")
    token_id: str = event["payload"]["token_id"]
    return token_id


def _redis_run[T](coro: Coroutine[Any, Any, T]) -> T:
    """Same cache-clear-around-`asyncio.run()` pattern
    `test_confirmations_route.py` uses: only safe once the one turn this
    helper checks has already finished, since it clears the loop-bound
    `get_redis`/`get_engine` caches `app_client`'s own portal loop needs."""
    get_redis.cache_clear()
    get_engine.cache_clear()
    try:
        return asyncio.run(coro)
    finally:
        get_redis.cache_clear()
        get_engine.cache_clear()


def test_lock_confirm_unlock_otp_block_replace(
    app_client: TestClient,
    it_accounts: dict[str, ItAccount],
    it_db: str,
    restore_cards: set[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEMO_OTP_CODE", _DEMO_OTP_CODE)
    get_settings.cache_clear()
    dsn = _psycopg_dsn(it_db)
    restore_cards.add(_MULTI_CARD_ID)

    app_client.app.state.turn_host.llm = ScriptedLLM(
        {
            "nlu": [
                NLUResult(
                    language="es",
                    intents=["card_block"],
                    status="clear",
                    slots=NLUSlots(card_hint="credit", block_kind="temporary_lock"),
                ),
                NLUResult(
                    language="es",
                    intents=["card_unlock"],
                    status="clear",
                    slots=NLUSlots(card_hint="credit"),
                ),
                NLUResult(
                    language="es",
                    intents=["card_block"],
                    status="clear",
                    slots=NLUSlots(card_hint="credit", block_kind="permanent_block"),
                ),
                NLUResult(language="es", intents=["affirm"], status="clear"),
                NLUResult(language="es", intents=["deny"], status="clear"),
            ]
        }
    )

    account = it_accounts[_MULTI_CUSTOMER_ID]
    csrf = _login(app_client, account)
    create_response = app_client.post("/api/v1/conversations", json={}, headers={CSRF_HEADER: csrf})
    assert create_response.status_code == 201
    conversation_id = create_response.json()["conversation_id"]
    base_url = f"/api/v1/conversations/{conversation_id}"

    # --- Step 3 (end-of-day): lock -> ui.confirm -> /confirmations -> done ---
    lock_response = app_client.post(
        f"{base_url}/messages",
        json={"text": "bloquea mi tarjeta de credito"},
        headers={CSRF_HEADER: csrf},
    )
    assert lock_response.status_code == 202
    lock_ask = _wait_for_bot_message(dsn, lock_response.json()["turn_id"])
    lock_token = _confirm_token(lock_ask["ui_payload"])

    lock_confirm_response = app_client.post(
        f"{base_url}/confirmations/{lock_token}",
        json={"decision": "confirm"},
        headers={CSRF_HEADER: csrf},
    )
    assert lock_confirm_response.status_code == 202
    lock_done = _wait_for_bot_message(dsn, lock_confirm_response.json()["turn_id"])
    # R3: this "listo" text only ever comes from a verified read-back.
    assert re.search(r"quedó bloqueada temporalmente a las \d{2}:\d{2}\.", lock_done["content"])

    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        lock_row = conn.execute(
            "SELECT locked FROM app.card_controls WHERE product_id = %s", (_MULTI_CARD_ID,)
        ).fetchone()
    assert lock_row is not None
    assert lock_row["locked"] is True

    # --- Step 4: unlock -> otp_required -> /auth/otp/verify -> resume -> confirm ---
    unlock_response = app_client.post(
        f"{base_url}/messages",
        json={"text": "desbloquea mi tarjeta de credito"},
        headers={CSRF_HEADER: csrf},
    )
    unlock_otp_ask = _wait_for_bot_message(dsn, unlock_response.json()["turn_id"])
    assert unlock_otp_ask["content"] == get_template("otp_required", "es")
    assert [event["kind"] for event in unlock_otp_ask["ui_payload"]] == ["otp_required"]

    otp_response = app_client.post(
        "/api/v1/auth/otp/verify", json={"code": _DEMO_OTP_CODE}, headers={CSRF_HEADER: csrf}
    )
    assert otp_response.status_code == 200
    csrf = otp_response.cookies["csrf_token"]

    resume_response = app_client.post(
        f"{base_url}/messages", json={"resume": "step_up"}, headers={CSRF_HEADER: csrf}
    )
    unlock_ask = _wait_for_bot_message(dsn, resume_response.json()["turn_id"])
    unlock_token = _confirm_token(unlock_ask["ui_payload"])

    unlock_confirm_response = app_client.post(
        f"{base_url}/confirmations/{unlock_token}",
        json={"decision": "confirm"},
        headers={CSRF_HEADER: csrf},
    )
    unlock_done = _wait_for_bot_message(dsn, unlock_confirm_response.json()["turn_id"])
    assert re.search(r"quedó desbloqueada a las \d{2}:\d{2}\.", unlock_done["content"])

    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        unlock_row = conn.execute(
            "SELECT locked FROM app.card_controls WHERE product_id = %s", (_MULTI_CARD_ID,)
        ).fetchone()
    assert unlock_row is not None
    assert unlock_row["locked"] is False

    # --- A fresh session: re-login, no step-up, before the address OTP below ---
    csrf = _login(app_client, account)

    # --- Step 5: lost card -> block -> replacement, changed address needs OTP ---
    block_response = app_client.post(
        f"{base_url}/messages",
        json={"text": "la perdi, bloqueala para siempre"},
        headers={CSRF_HEADER: csrf},
    )
    block_ask = _wait_for_bot_message(dsn, block_response.json()["turn_id"])
    block_token = _confirm_token(block_ask["ui_payload"])

    block_confirm_response = app_client.post(
        f"{base_url}/confirmations/{block_token}",
        json={"decision": "confirm"},
        headers={CSRF_HEADER: csrf},
    )
    block_done = _wait_for_bot_message(dsn, block_confirm_response.json()["turn_id"])
    assert "bloqueada de forma permanente" in block_done["content"]
    assert "6475" in block_done["content"]

    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        status_row = conn.execute(
            "SELECT product_status FROM bank.products WHERE product_id = %s", (_MULTI_CARD_ID,)
        ).fetchone()
        history_count = conn.execute(
            "SELECT count(*) AS n FROM app.card_status_history WHERE product_id = %s",
            (_MULTI_CARD_ID,),
        ).fetchone()
    assert status_row is not None
    assert status_row["product_status"] == "Blocked"
    assert history_count is not None
    assert history_count["n"] == 1

    accept_response = app_client.post(
        f"{base_url}/messages", json={"text": "si"}, headers={CSRF_HEADER: csrf}
    )
    accept_ask = _wait_for_bot_message(dsn, accept_response.json()["turn_id"])
    assert accept_ask["ui_payload"] is None  # address_confirm question, no plan yet

    deny_on_file_response = app_client.post(
        f"{base_url}/messages", json={"text": "no"}, headers={CSRF_HEADER: csrf}
    )
    address_otp_ask = _wait_for_bot_message(dsn, deny_on_file_response.json()["turn_id"])
    assert address_otp_ask["content"] == get_template("otp_required", "es")
    assert [event["kind"] for event in address_otp_ask["ui_payload"]] == ["otp_required"]

    otp_response_2 = app_client.post(
        "/api/v1/auth/otp/verify", json={"code": _DEMO_OTP_CODE}, headers={CSRF_HEADER: csrf}
    )
    assert otp_response_2.status_code == 200
    csrf = otp_response_2.cookies["csrf_token"]

    address_ask_response = app_client.post(
        f"{base_url}/messages", json={"resume": "step_up"}, headers={CSRF_HEADER: csrf}
    )
    address_ask = _wait_for_bot_message(dsn, address_ask_response.json()["turn_id"])
    assert address_ask["content"] == get_template("address_ask", "es")

    address_response = app_client.post(
        f"{base_url}/messages",
        json={"text": "Av. Reforma 123, CDMX"},
        headers={CSRF_HEADER: csrf},
    )
    replacement_confirm_ask = _wait_for_bot_message(dsn, address_response.json()["turn_id"])
    # R5: the raw address text never reaches a reply.
    assert "Av. Reforma 123" not in replacement_confirm_ask["content"]
    replacement_token = _confirm_token(replacement_confirm_ask["ui_payload"])

    replacement_confirm_response = app_client.post(
        f"{base_url}/confirmations/{replacement_token}",
        json={"decision": "confirm"},
        headers={CSRF_HEADER: csrf},
    )
    replacement_done = _wait_for_bot_message(dsn, replacement_confirm_response.json()["turn_id"])
    assert re.search(r"RPL-[0-9A-F]+", replacement_done["content"])

    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        replacement_row = conn.execute(
            "SELECT address_changed, tracking_id FROM app.card_replacements WHERE product_id = %s",
            (_MULTI_CARD_ID,),
        ).fetchone()
    assert replacement_row is not None
    assert replacement_row["address_changed"] is True
    assert replacement_row["tracking_id"] in replacement_done["content"]

    # --- Every write this test made left an audited tool_call/tool_result
    # pair, all stamped with the same policy hash (D2, D13, D14). ---
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        events = conn.execute(
            "SELECT type, policy_version FROM audit.audit_events WHERE conversation_id = %s",
            (uuid.UUID(conversation_id),),
        ).fetchall()
    types = [event["type"] for event in events]
    assert types.count("tool_call") > 0
    assert types.count("tool_call") == types.count("tool_result")
    policy_versions = {event["policy_version"] for event in events}
    assert len(policy_versions) == 1
    assert next(iter(policy_versions)).startswith("sha256:")


def test_pt_lock_happy_path(
    app_client: TestClient,
    it_accounts: dict[str, ItAccount],
    it_db: str,
    restore_cards: set[str],
) -> None:
    dsn = _psycopg_dsn(it_db)
    restore_cards.add(_SINGLE_CARD_ID)

    app_client.app.state.turn_host.llm = ScriptedLLM(
        {
            "nlu": [
                NLUResult(
                    language="pt",
                    intents=["card_block"],
                    status="clear",
                    slots=NLUSlots(block_kind="temporary_lock"),
                )
            ]
        }
    )

    account = it_accounts[_SINGLE_CUSTOMER_ID]
    csrf = _login(app_client, account)
    create_response = app_client.post("/api/v1/conversations", json={}, headers={CSRF_HEADER: csrf})
    assert create_response.status_code == 201
    base_url = f"/api/v1/conversations/{create_response.json()['conversation_id']}"

    lock_response = app_client.post(
        f"{base_url}/messages",
        json={"text": "quero bloquear meu cartao temporariamente"},
        headers={CSRF_HEADER: csrf},
    )
    lock_ask = _wait_for_bot_message(dsn, lock_response.json()["turn_id"])
    lock_token = _confirm_token(lock_ask["ui_payload"])

    lock_confirm_response = app_client.post(
        f"{base_url}/confirmations/{lock_token}",
        json={"decision": "confirm"},
        headers={CSRF_HEADER: csrf},
    )
    lock_done = _wait_for_bot_message(dsn, lock_confirm_response.json()["turn_id"])
    assert re.search(r"ficou bloqueado temporariamente às \d{2}:\d{2}\.", lock_done["content"])
    assert "2222" in lock_done["content"]

    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        lock_row = conn.execute(
            "SELECT locked FROM app.card_controls WHERE product_id = %s", (_SINGLE_CARD_ID,)
        ).fetchone()
    assert lock_row is not None
    assert lock_row["locked"] is True


def test_bank_blocked_unlock_handoff(
    app_client: TestClient,
    it_accounts: dict[str, ItAccount],
    it_db: str,
    restore_cards: set[str],
) -> None:
    dsn = _psycopg_dsn(it_db)
    restore_cards.add(_BLOCKED_CARD_ID)

    app_client.app.state.turn_host.llm = ScriptedLLM(
        {
            "nlu": [NLUResult(language="es", intents=["card_unlock"], status="clear")],
            "handoff_summary": [
                HandoffSummaryDraft(
                    request="La tarjeta tiene un bloqueo del banco.",
                    asked="Pidió ayuda.",
                    did="Nada.",
                    unfinished="Todo.",
                )
            ],
        }
    )

    account = it_accounts[_BLOCKED_CUSTOMER_ID]
    csrf = _login(app_client, account)
    create_response = app_client.post("/api/v1/conversations", json={}, headers={CSRF_HEADER: csrf})
    assert create_response.status_code == 201
    conversation_id = create_response.json()["conversation_id"]
    base_url = f"/api/v1/conversations/{conversation_id}"

    unlock_response = app_client.post(
        f"{base_url}/messages",
        json={"text": "quiero desbloquear mi tarjeta"},
        headers={CSRF_HEADER: csrf},
    )
    handoff = _wait_for_bot_message(dsn, unlock_response.json()["turn_id"])
    assert "Fraudes" in handoff["content"]
    # No ui.confirm (no plan was ever issued); the only UI is the handoff banner.
    assert [event["kind"] for event in handoff["ui_payload"]] == ["handoff_banner"]

    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        rows = conn.execute(
            "SELECT queue, reason, status FROM app.handoffs WHERE conversation_id = %s",
            (uuid.UUID(conversation_id),),
        ).fetchall()
    assert rows == [{"queue": "fraudes", "reason": "bank_side_block", "status": "queued"}]

    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        for table in ("app.card_controls", "app.card_status_history", "app.card_replacements"):
            count = conn.execute(
                f"SELECT count(*) AS n FROM {table} WHERE product_id = %s", (_BLOCKED_CARD_ID,)
            ).fetchone()
            assert count is not None
            assert count["n"] == 0

    async def _no_open_plan() -> bool:
        return bool([key async for key in get_redis().scan_iter(match="conf:*")])

    assert _redis_run(_no_open_plan()) is False
