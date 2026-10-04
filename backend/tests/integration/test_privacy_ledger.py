"""D5-A A1 ledger proof over the HTTP API (D5-D7, D9).

One customer turn carries a card number through the real app with a stub chat
model behind the real `StructuredLLMClient` and `AuditLLMCallSink`. The ledger
rows and the stored message hold only the token; the vault restores the
number; the claiming agent's transcript shows the raw text. A second turn asks
for a person so there is a handoff to claim (the transcript route is
claimant-only).

See `docs/specs/d5-a-privacy-grounding-eval.md` §"Test list".
"""

import re
import time
import uuid
from types import SimpleNamespace
from typing import Any

import psycopg
from fastapi.testclient import TestClient
from psycopg.rows import dict_row

from app.core.llm.client import StructuredLLMClient
from app.core.llm.settings import LLMSettings
from app.domains.audit.service import AuditLLMCallSink
from app.domains.conversation.nodes.compose import ComposeDraft
from app.domains.conversation.nodes.handoff_summary import HandoffSummaryDraft
from app.domains.conversation.schemas import NLUResult, NLUSlots
from app.domains.safety.vault import PostgresPiiVault
from tests.integration.conftest import ItAccount, ItStaff
from tests.integration.test_staff_round_trip import (
    _customer_login,
    _human_request_nlu,
    _open_conversation,
    _post_turn,
    _psycopg_dsn,
    _staff_login,
    _wait_for_handoff,
)

_SINGLE_CUSTOMER_ID = "CLI-TFSINGLE0002"
_PAN = "4111 1111 1111 1111"
_ASK = f"Mi tarjeta {_PAN} sigue activa?"
_WAIT_SECONDS = 20.0


class _StubRunnable:
    """Answers by schema, with `usage_metadata` on the raw message like a real provider."""

    def __init__(self, outputs: dict[type, list[Any]], schema: type) -> None:
        self._outputs = outputs
        self._schema = schema

    async def ainvoke(self, messages: Any) -> dict[str, Any]:
        raw = SimpleNamespace(usage_metadata={"input_tokens": 120, "output_tokens": 30})
        parsed = self._outputs[self._schema].pop(0)
        return {"raw": raw, "parsed": parsed, "parsing_error": None}


class _StubChatModel:
    def __init__(self, outputs: dict[type, list[Any]]) -> None:
        self._outputs = outputs

    def with_structured_output(
        self, schema: type, *, include_raw: bool = False, method: str | None = None
    ) -> _StubRunnable:
        return _StubRunnable(self._outputs, schema)


def _wait_for_rows(dsn: str, sql: str, params: tuple[Any, ...], *, minimum: int) -> list[Any]:
    deadline = time.monotonic() + _WAIT_SECONDS
    while True:
        with psycopg.connect(dsn, row_factory=dict_row) as conn:
            rows = conn.execute(sql, params).fetchall()  # type: ignore[arg-type]
        if len(rows) >= minimum:
            return rows
        if time.monotonic() > deadline:
            raise AssertionError(f"expected {minimum} rows within {_WAIT_SECONDS}s, got {rows}")
        time.sleep(0.1)


def test_turn_writes_masked_ledger_and_encrypted_messages(
    app_client: TestClient,
    it_accounts: dict[str, ItAccount],
    it_staff: dict[str, ItStaff],
    it_db: str,
) -> None:
    dsn = _psycopg_dsn(it_db)
    outputs: dict[type, list[Any]] = {
        NLUResult: [
            NLUResult(language="es", intents=["card_status"], status="clear", slots=NLUSlots()),
            _human_request_nlu("es"),
        ],
        ComposeDraft: [ComposeDraft(text="Tu tarjeta {card_kind} {card_mask} esta {status}.")],
        HandoffSummaryDraft: [
            HandoffSummaryDraft(
                request="El cliente pidió hablar con alguien.",
                asked="Pidió ayuda.",
                did="Nada.",
                unfinished="Todo.",
            )
        ],
    }
    app_client.app.state.turn_host.llm = StructuredLLMClient(  # type: ignore[attr-defined]
        LLMSettings(_env_file=None),
        chat_model_factory=lambda settings, step: _StubChatModel(outputs),
        sink=AuditLLMCallSink(),
    )
    customer = _customer_login(app_client, it_accounts[_SINGLE_CUSTOMER_ID])
    conversation_id = _open_conversation(app_client, customer)

    turn_id = _post_turn(app_client, customer, conversation_id, _ASK)
    _wait_for_rows(
        dsn,
        "SELECT 1 FROM app.messages WHERE turn_id = %s AND role = 'bot'",
        (uuid.UUID(turn_id),),
        minimum=1,
    )

    # One ledger row per call (NLU, compose), each with the full record and
    # only the token in `input_text`.
    calls = _wait_for_rows(
        dsn,
        "SELECT step, status, model_id, prompt_version, input_tokens, output_tokens, cost_usd,"
        " latency_ms, input_text FROM audit.llm_calls WHERE conversation_id = %s ORDER BY at",
        (uuid.UUID(conversation_id),),
        minimum=2,
    )
    assert [c["step"] for c in calls] == ["nlu", "compose"]
    for call in calls:
        assert call["status"] == "ok"
        assert call["model_id"] and call["prompt_version"]
        assert (call["input_tokens"], call["output_tokens"]) == (120, 30)
        assert call["cost_usd"] is not None and call["cost_usd"] > 0
        assert call["latency_ms"] is not None
    assert "⟨CARD_1⟩" in calls[0]["input_text"]
    assert all("4111" not in (c["input_text"] or "") for c in calls)

    # `reply_sent` carries the code-written values (the card mask's last 4
    # digits of the customer's own card, not the typed PAN) and the turn's grounding outcome.
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        sent = conn.execute(
            "SELECT payload, sources FROM audit.audit_events"
            " WHERE type = 'reply_sent' AND turn_id = %s",
            (uuid.UUID(turn_id),),
        ).fetchone()
    assert sent is not None
    payload = sent["payload"]
    assert any(re.fullmatch(r"•+ ?\d{4}", value) for value in payload["fact_values"]), payload
    assert _PAN not in payload["fact_values"]
    assert payload["grounding"]["outcome"] in {"ok", "regenerated", "template"}
    # ...and the facts' provenance, the staff timeline's "why" sources (D7-A D20).
    assert sent["sources"], sent
    assert all(_PAN not in source for source in sent["sources"])

    # The stored customer message is encrypted; the masked copy holds the token.
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        message = conn.execute(
            "SELECT content, content_masked FROM app.messages"
            " WHERE conversation_id = %s AND role = 'customer'",
            (uuid.UUID(conversation_id),),
        ).fetchone()
    assert message is not None
    assert message["content"] != _ASK and "4111" not in message["content"]
    assert "⟨CARD_1⟩" in message["content_masked"] and "4111" not in message["content_masked"]

    # The vault restores the number (the engine is bound to the app's portal loop).
    vault = PostgresPiiVault(uuid.UUID(conversation_id))
    restored = app_client.portal.call(vault.unmask, message["content_masked"])  # type: ignore[union-attr]
    assert _PAN in restored

    # A claiming agent reads the raw text.
    _post_turn(app_client, customer, conversation_id, "Quiero hablar con una persona")
    row = _wait_for_handoff(dsn, conversation_id)
    staff = _staff_login(app_client, it_staff["atencion"])
    claim = app_client.post(f"/api/v1/staff/handoffs/{row['id']}/claim", headers=staff)
    assert claim.status_code == 200, claim.text
    transcript = app_client.get(
        f"/api/v1/staff/conversations/{conversation_id}/messages", headers=staff
    )
    assert transcript.status_code == 200, transcript.text
    assert ("customer", _ASK) in [(m["role"], m["text"]) for m in transcript.json()]
