"""Fault-injection and reliability-knob tests (D6-A); later tasks append here."""

import asyncio
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.config import get_settings
from app.core.llm.client import StructuredLLMClient
from app.core.llm.settings import LLMSettings
from app.core.llm.sink import LLMCallRecord
from app.domains.conversation.graph import ConfirmationDecision, GraphState, run_turn
from app.domains.conversation.nodes.fallback import fallback
from app.domains.conversation.nodes.handoff_summary import HandoffSummaryDraft
from app.domains.conversation.nodes.load_session import _guess_language
from app.domains.conversation.schemas import NLUResult, NLUSlots
from app.domains.conversation.templates import get_template
from app.main import create_app
from tests.conftest import ScriptedLLM, make_session


@pytest.fixture
def reset_settings() -> Iterator[None]:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_faults_refused_in_prod(monkeypatch: pytest.MonkeyPatch, reset_settings: None) -> None:
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("FAULTS", "cards_write_error")
    for name in ("JWT_SECRET", "IDENTITY_HMAC_KEY", "PII_VAULT_KEY"):
        monkeypatch.setenv(name, "x")
    get_settings.cache_clear()
    with pytest.raises(RuntimeError, match="FAULTS is set under APP_ENV=prod"):
        with TestClient(create_app()):
            pass

    monkeypatch.setenv("FAULTS", "bogus")
    get_settings.cache_clear()
    with pytest.raises(ValidationError):
        get_settings()


def test_llm_disabled_every_turn_falls_back(
    monkeypatch: pytest.MonkeyPatch, reset_settings: None, fakebank_dir: Path
) -> None:
    """D10: under LLM_DISABLED a typed turn and a button confirmation both get the
    failure text and a handoff, with zero LLM calls and nothing written."""
    failure = get_template("failure_handoff", "es")
    transfer_prefix = get_template("handoff_transfer", "es").split("{queue_label}")[0]

    async def run() -> None:
        # (1) typed turn
        monkeypatch.setenv("LLM_DISABLED", "true")
        get_settings.cache_clear()
        llm = ScriptedLLM()
        session = make_session("CLI-TFSINGLE0002", fakebank_dir, llm)
        reply, _ = await run_turn(session.graph, "bloquea mi tarjeta", config=session.config)
        assert llm.calls == []
        assert reply.startswith(failure)
        assert transfer_prefix in reply
        assert len(session.handoff_tools.created) == 1
        packet = session.handoff_tools.created[0]
        assert packet.reason == "llm_unavailable"
        assert packet.queue == "atencion"

        # (2) plan issued with the LLM on, then the kill switch, then the button
        monkeypatch.setenv("LLM_DISABLED", "false")
        get_settings.cache_clear()
        llm2 = ScriptedLLM(
            {
                "nlu": [
                    NLUResult(
                        language="es",
                        intents=["card_block"],
                        status="clear",
                        slots=NLUSlots(block_kind="temporary_lock"),
                    )
                ]
            }
        )
        session2 = make_session("CLI-TFSINGLE0002", fakebank_dir, llm2)
        _, debug = await run_turn(session2.graph, "bloquea mi tarjeta", config=session2.config)
        assert debug.pending == "card_block.confirmation"
        state = await session2.graph.aget_state(session2.config)
        token_id = state.values["confirmation_token_id"]
        calls_before = len(llm2.calls)

        monkeypatch.setenv("LLM_DISABLED", "true")
        get_settings.cache_clear()
        reply2, _ = await run_turn(
            session2.graph,
            "",
            config=session2.config,
            confirmation=ConfirmationDecision(token_id=token_id, decision="confirm"),
        )
        assert len(llm2.calls) == calls_before
        assert reply2.startswith(failure)
        assert session2.handoff_tools.created[0].reason == "llm_unavailable"
        assert not session2.overlay.locked

        # (3) fresh session, no previous language: a PT first turn gets the PT text
        llm3 = ScriptedLLM()
        session3 = make_session("CLI-TFSINGLE0002", fakebank_dir, llm3)
        reply3, _ = await run_turn(
            session3.graph, "quero bloquear meu cartão", config=session3.config
        )
        assert llm3.calls == []
        assert reply3.startswith(get_template("failure_handoff", "pt"))

        # (4) the after-action text needs an action verified THIS turn (D9): one at
        # an index >= actions_at_turn_start counts, one from an earlier turn does not.
        verified = SimpleNamespace(verified=True)
        base = {"language": "es", "escalation_reason": "tool_failure"}
        this_turn = cast(GraphState, {**base, "actions": [verified], "actions_at_turn_start": 0})
        earlier = cast(GraphState, {**base, "actions": [verified], "actions_at_turn_start": 1})
        assert fallback(this_turn)["segments"] == [
            get_template("failure_handoff_after_action", "es")
        ]
        assert fallback(earlier)["segments"] == [get_template("failure_handoff", "es")]

        for text, expected in [
            ("quiero bloquear mi tarjeta", "es"),
            ("está bloqueada mi tarjeta", "es"),
            ("necesito ayuda con un pago", "es"),
            ("hola", "es"),
            ("quero bloquear meu cartão", "pt"),
            ("perdi meu cartao", "pt"),
            ("minha fatura", "pt"),
        ]:
            assert _guess_language(text) == expected, text

    asyncio.run(run())


async def _no_sleep(_: float) -> None:
    return None


class _ForbiddenChatModel:
    """A chat model that records `ainvoke`; `bedrock_timeout` must never reach it."""

    def __init__(self) -> None:
        self.invoked = 0

    def with_structured_output(self, *args: Any, **kwargs: Any) -> "_ForbiddenChatModel":
        return self

    async def ainvoke(self, messages: Any) -> Any:
        self.invoked += 1
        raise AssertionError("bedrock_timeout must not reach the chat model")


class _RecordingSink:
    def __init__(self) -> None:
        self.rows: list[LLMCallRecord] = []

    async def record(self, call: LLMCallRecord) -> None:
        self.rows.append(call)


def _lock_llm(language: str, summary: str) -> ScriptedLLM:
    return ScriptedLLM(
        {
            "nlu": [
                NLUResult(
                    language=language,  # type: ignore[arg-type]
                    intents=["card_block"],
                    status="clear",
                    slots=NLUSlots(block_kind="temporary_lock"),
                )
            ],
            "handoff_summary": [HandoffSummaryDraft(request=summary)],
        }
    )


async def _confirm_lock(session: Any, text: str) -> str:
    _, debug = await run_turn(session.graph, text, config=session.config)
    assert debug.pending == "card_block.confirmation"
    state = await session.graph.aget_state(session.config)
    reply, _ = await run_turn(
        session.graph,
        "",
        config=session.config,
        confirmation=ConfirmationDecision(
            token_id=state.values["confirmation_token_id"], decision="confirm"
        ),
    )
    return str(reply)


def test_bedrock_timeout_fallback_handoff_es(
    monkeypatch: pytest.MonkeyPatch, reset_settings: None, fakebank_dir: Path
) -> None:
    """A1 Done-when, fault 1: nlu and handoff_summary each fail 3 times (all
    `unavailable`), the chat model is never invoked, and the customer gets the
    failure text, the transfer text and an `llm_unavailable` packet."""
    monkeypatch.setenv("FAULTS", "bedrock_timeout")
    get_settings.cache_clear()
    chat_model = _ForbiddenChatModel()
    sink = _RecordingSink()
    sleeps: list[float] = []

    async def record_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    llm = StructuredLLMClient(
        LLMSettings(_env_file=None),
        chat_model_factory=lambda settings, step: chat_model,
        sink=sink,
        sleep=record_sleep,
    )

    async def run() -> None:
        session = make_session("CLI-TFSINGLE0002", fakebank_dir, llm)  # type: ignore[arg-type]
        reply, _ = await run_turn(session.graph, "bloquea mi tarjeta", config=session.config)
        assert [(r.step, r.attempt, r.status) for r in sink.rows] == [
            ("nlu", 1, "unavailable"),
            ("nlu", 2, "unavailable"),
            ("nlu", 3, "unavailable"),
            ("handoff_summary", 1, "unavailable"),
            ("handoff_summary", 2, "unavailable"),
            ("handoff_summary", 3, "unavailable"),
        ]
        assert len(sleeps) == 4
        assert chat_model.invoked == 0
        failure = get_template("failure_handoff", "es")
        assert reply.startswith(failure)
        assert get_template("handoff_transfer", "es").split("{queue_label}")[0] in reply
        assert len(session.handoff_tools.created) == 1
        packet = session.handoff_tools.created[0]
        assert packet.reason == "llm_unavailable"
        assert packet.queue == "atencion"

    asyncio.run(run())


def test_cards_write_error_fallback_handoff_pt(
    monkeypatch: pytest.MonkeyPatch, reset_settings: None, fakebank_dir: Path
) -> None:
    """A1 Done-when, fault 2: a confirmed PT lock fails 3 times, nothing is
    locked, and the customer is handed off with `tool_failure`."""
    monkeypatch.setenv("FAULTS", "cards_write_error")
    get_settings.cache_clear()
    llm = ScriptedLLM(
        {
            "nlu": [
                NLUResult(
                    language="pt",
                    intents=["card_block"],
                    status="clear",
                    slots=NLUSlots(block_kind="temporary_lock"),
                ),
                NLUResult(language="pt", intents=["greeting"], status="clear", slots=NLUSlots()),
            ],
            "handoff_summary": [HandoffSummaryDraft(request="Falha ao bloquear em {queue_label}.")],
        }
    )

    async def run() -> None:
        session = make_session(
            "CLI-TFSINGLE0002", fakebank_dir, llm, write_audit=True, sleep=_no_sleep
        )
        reply = await _confirm_lock(session, "quero bloquear meu cartão")
        results = [
            p
            for t, p in session.audit.events
            if t == "tool_result" and p.get("tool") == "cards.lock_card"
        ]
        assert len(results) == 3
        assert all("error" in p for p in results)
        assert [p["attempt"] for p in results] == [1, 2, 3]
        assert reply.startswith(get_template("failure_handoff_after_action", "pt"))
        assert "Não fiz nenhuma alteração" not in reply
        assert session.handoff_tools.created[0].reason == "tool_failure"
        assert not session.overlay.locked
        state = await session.graph.aget_state(session.config)
        assert state.values["write_failed"] is True

        # `write_failed` is per turn: after an agent hands the conversation back
        # (simulated by setting mode=bot), a later non-failing turn must reset it.
        await session.graph.aupdate_state(session.config, {"mode": "bot"})
        await run_turn(session.graph, "oi", config=session.config)
        state = await session.graph.aget_state(session.config)
        assert state.values["write_failed"] is False

    asyncio.run(run())


def test_readback_mismatch_action_unverified_es(
    monkeypatch: pytest.MonkeyPatch, reset_settings: None, fakebank_dir: Path
) -> None:
    """A1 Done-when, fault 3, D7: an unverified read-back is one attempt, never
    retried, and hands off as `action_unverified`."""
    monkeypatch.setenv("FAULTS", "readback_mismatch")
    get_settings.cache_clear()
    llm = _lock_llm("es", "Bloqueo sin verificar en {queue_label}.")

    async def run() -> None:
        session = make_session(
            "CLI-TFSINGLE0002", fakebank_dir, llm, write_audit=True, sleep=_no_sleep
        )
        reply = await _confirm_lock(session, "bloquea mi tarjeta")
        results = [
            p
            for t, p in session.audit.events
            if t == "tool_result" and p.get("tool") == "cards.lock_card"
        ]
        assert len(results) == 1
        assert results[0]["verified"] is False
        assert not any(p.get("attempt") == 2 for p in results)
        assert session.handoff_tools.created[0].reason == "action_unverified"
        # The reply is the ES transfer text: no PT, and no "done" wording (R3).
        assert get_template("handoff_transfer", "es").split("{queue_label}")[0] in reply
        assert get_template("handoff_transfer", "pt").split("{queue_label}")[0] not in reply
        assert "bloqueada" not in reply.lower()

    asyncio.run(run())
