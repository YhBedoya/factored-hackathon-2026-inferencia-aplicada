"""D11: `429 turn_cap_reached` once a bot-mode conversation hits its cap.
Human-mode posts neither check nor count.

Redis reads run on `app_client`'s own portal loop (`get_redis()` is
loop-bound), same as `test_session_resume.py`.

See `docs/specs/d6-a-reliability-resume-injection-dq.md` D11.
"""

import time
import uuid

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.rows import dict_row

from app.core.config import get_settings
from app.core.redis import get_redis
from app.domains.conversation.nodes.compose import ComposeDraft
from app.domains.conversation.nodes.handoff_summary import HandoffSummaryDraft
from app.domains.conversation.schemas import NLUResult, NLUSlots
from app.domains.identity.tokens import CSRF_HEADER
from tests.conftest import ScriptedLLM
from tests.integration.conftest import ItAccount
from tests.integration.test_write_path_api import _login, _psycopg_dsn, _wait_for_bot_message

_CUSTOMER_ID = "CLI-TFSINGLE0002"
_CAP = 2


def _post(
    client: TestClient, csrf: str, conversation_id: str, text: str
) -> tuple[int, dict[str, str]]:
    response = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"text": text},
        headers={CSRF_HEADER: csrf},
    )
    return response.status_code, response.json()


def _message_count(dsn: str, conversation_id: str) -> int:
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        row = conn.execute(
            "SELECT count(*) AS n FROM app.messages WHERE conversation_id = %s",
            (uuid.UUID(conversation_id),),
        ).fetchone()
    assert row is not None
    return int(row["n"])


def _wait_for_mode(dsn: str, conversation_id: str, mode: str) -> None:
    deadline = time.monotonic() + 20
    while True:
        with psycopg.connect(dsn, row_factory=dict_row) as conn:
            row = conn.execute(
                "SELECT mode FROM app.conversations WHERE id = %s", (uuid.UUID(conversation_id),)
            ).fetchone()
        if row is not None and row["mode"] == mode:
            return
        assert time.monotonic() < deadline, f"conversation never reached mode {mode}"
        time.sleep(0.1)


def _redis_state(client: TestClient, conversation_id: str) -> tuple[int, int]:
    """`(conversation counter, turn lock exists)`."""

    async def _read() -> tuple[int, int]:
        redis = get_redis()
        counter = await redis.get(f"turns:conv:{conversation_id}")
        return int(counter or 0), int(await redis.exists(f"turn:{conversation_id}"))

    assert client.portal is not None
    result: tuple[int, int] = client.portal.call(_read)
    return result


def test_cap_returns_429_bot_mode_only(
    app_client: TestClient,
    it_accounts: dict[str, ItAccount],
    it_db: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TURN_CAP_PER_CONVERSATION", str(_CAP))
    get_settings.cache_clear()
    dsn = _psycopg_dsn(it_db)
    card_status = NLUResult(
        language="es", intents=["card_status"], status="clear", slots=NLUSlots()
    )
    human_request = NLUResult(
        language="es", intents=["human_request"], status="clear", slots=NLUSlots()
    )
    app_client.app.state.turn_host.llm = ScriptedLLM(  # type: ignore[attr-defined]
        {
            "nlu": [card_status, card_status, human_request],
            "compose": [ComposeDraft(text="Tu tarjeta {card_kind} {card_mask} esta {status}.")] * 2,
            "handoff_summary": [
                HandoffSummaryDraft(request="El cliente pidió hablar con alguien.")
            ],
        }
    )
    csrf = _login(app_client, it_accounts[_CUSTOMER_ID])

    def _open() -> str:
        create = app_client.post("/api/v1/conversations", json={}, headers={CSRF_HEADER: csrf})
        assert create.status_code == 201
        return str(create.json()["conversation_id"])

    # --- Bot mode: two turns fit, the third is refused and schedules nothing. ---
    bot_conversation = _open()
    for _ in range(_CAP):
        status, body = _post(app_client, csrf, bot_conversation, "estado de mi tarjeta")
        assert status == 202
        _wait_for_bot_message(dsn, body["turn_id"])
    before = _message_count(dsn, bot_conversation)
    status, body = _post(app_client, csrf, bot_conversation, "otra vez")
    assert (status, body) == (429, {"detail": "turn_cap_reached"})
    assert _message_count(dsn, bot_conversation) == before
    assert _redis_state(app_client, bot_conversation) == (_CAP, 0)

    # --- Human mode: past the cap, posts still go through and don't count. ---
    human_conversation = _open()
    status, body = _post(app_client, csrf, human_conversation, "quiero hablar con una persona")
    assert status == 202
    _wait_for_bot_message(dsn, body["turn_id"])
    _wait_for_mode(dsn, human_conversation, "human")
    counted, _ = _redis_state(app_client, human_conversation)
    assert counted == 1
    for _ in range(_CAP + 1):
        deadline = time.monotonic() + 20
        while True:
            status, _body = _post(app_client, csrf, human_conversation, "hola?")
            if status != 409:  # previous human-mode turn still holds the lock
                break
            assert time.monotonic() < deadline
            time.sleep(0.1)
        assert status == 202
    assert _redis_state(app_client, human_conversation)[0] == counted
