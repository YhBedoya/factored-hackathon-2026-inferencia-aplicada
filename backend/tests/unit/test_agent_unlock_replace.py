"""S2 tests 3, 4 and 5: the unlock and replacement conversations through the agent
(OTP pause, address turn, Acepto) and the declined permanent-block offer. Fake LLM only."""

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, Literal

import pytest

from app.core.db import get_engine
from app.domains.conversation.agent.schema import AgentTurn
from app.domains.conversation.flows.actions import OFFER_REPLACEMENT_PAUSE
from app.domains.conversation.graph import ConfirmationDecision, run_turn
from app.domains.conversation.schemas import NLUResult
from app.domains.conversation.templates import Language, get_template
from app.domains.safety.vault import InMemoryPiiVault
from tests.conftest import AgentScript, ScriptedLLM, Session, make_session, run_recorded_turn

_Events = list[tuple[str, dict[str, Any]]]
_OTP = "000000"
_SINGLE_CARD = "PRD-TFS2CRED0001"
_MULTI_CARD = "PRD-TFM1CRED0001"


def _turn(
    language: Language,
    intents: list[Any],
    reply: str,
    *,
    reported_done: list[int] | None = None,
) -> AgentTurn:
    lang: Literal["es", "pt"] = language
    return AgentTurn(
        language=lang,
        intents=intents,
        outcome="answered",
        awaiting_slot=None,
        reported_done=reported_done or [],
        reply=reply,
    )


def _one(events: _Events, kind: str) -> dict[str, Any]:
    return next(p for t, p in events if t == kind)


async def _open_plan(session: Session) -> tuple[Any, Any]:
    values = (await session.graph.aget_state(session.config)).values
    return values["confirmation_token_id"], values["open_question"]["ui"]


def _spy_unmask(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """The runner unmasks exactly the reply it sends; record each one."""
    sent: list[str] = []
    unmask = InMemoryPiiVault.unmask

    async def _spy(self: InMemoryPiiVault, text: str) -> str:
        sent.append(text)
        return await unmask(self, text)

    monkeypatch.setattr(InMemoryPiiVault, "unmask", _spy)
    return sent


async def _ui_kinds(session: Session) -> list[str]:
    values = (await session.graph.aget_state(session.config)).values
    return [event.kind for event in values.get("ui") or []]


async def _accept(session: Session, monkeypatch: pytest.MonkeyPatch) -> _Events:
    token, _ = await _open_plan(session)
    decision = ConfirmationDecision(token_id=token, decision="confirm")
    return await run_recorded_turn(session, monkeypatch, "", confirmation=decision)


def _in_one_loop(run: Callable[[], Awaitable[None]]) -> None:
    async def wrapped() -> None:
        try:
            await run()
        finally:
            await get_engine().dispose()

    asyncio.run(wrapped())


@pytest.mark.usefixtures("agent_on")
@pytest.mark.parametrize(
    ("language", "text"),
    [("es", "desbloquea mi tarjeta"), ("pt", "desbloqueie meu cartão")],
)
def test_unlock_happy(
    monkeypatch: pytest.MonkeyPatch, fakebank_dir: Path, language: Language, text: str
) -> None:
    async def run() -> None:
        rounds = [
            [("card_status", {})],
            [("propose_plan", {"steps": [{"action": "unlock", "card": "c1"}]})],
        ]
        first = _turn(language, ["card_unlock"], "Necesito verificar tu identidad.")
        shown = _turn(language, ["card_unlock"], "Revisa el desbloqueo de {c1_card_mask}.")
        done = _turn(language, ["card_unlock"], "Listo, desbloqueada.", reported_done=[0])
        llm = ScriptedLLM(
            {
                "agent": [
                    AgentScript(rounds=rounds, finals=[first]),
                    AgentScript(rounds=[], finals=[shown]),
                    AgentScript(rounds=[], finals=[done]),
                ]
            }
        )
        session = make_session(
            "CLI-TFSINGLE0002", fakebank_dir, llm, otp_code=_OTP, write_audit=True
        )
        session.overlay.locked.add(_SINGLE_CARD)

        await run_recorded_turn(session, monkeypatch, text)
        assert await _ui_kinds(session) == ["otp_required"]
        assert session.gate.verify(_OTP) is True
        reply, _ = await run_turn(session.graph, "", config=session.config, resume="step_up")
        assert "Revisa el desbloqueo" in reply
        _, ui = await _open_plan(session)
        assert len(ui) == 1 and ui[0].kind == "confirm"
        assert ui[0].payload.labels == "accept_decline"
        assert [s.tool for s in ui[0].payload.steps] == ["cards.unlock_card"]
        assert _SINGLE_CARD in session.overlay.locked

        e3 = await _accept(session, monkeypatch)
        assert [t for t, _ in e3].count("readback") == 1
        assert _SINGLE_CARD not in session.overlay.locked
        sent = _one(e3, "reply_sent")
        assert sent["path"] == "agent"
        assert {s["intent"]: s["status"] for s in sent["segments"]}["card_unlock"] == "resolved"

    _in_one_loop(run)


@pytest.mark.usefixtures("agent_on")
@pytest.mark.parametrize(
    ("language", "customer", "card_id", "address"),
    [
        ("es", "CLI-TFSINGLE0002", _SINGLE_CARD, "on_file"),
        ("pt", "CLI-TFMULTI00001", _MULTI_CARD, "new"),
    ],
)
def test_replace_happy(
    monkeypatch: pytest.MonkeyPatch,
    fakebank_dir: Path,
    language: Language,
    customer: str,
    card_id: str,
    address: str,
) -> None:
    async def run() -> None:
        step = {"action": "replace", "card": "c1", "address": address}
        rounds = [[("card_status", {})], [("propose_plan", {"steps": [step]})]]
        intents = ["replacement_request"]
        finals = [
            _turn(language, intents, "Voy a pedir la reposición."),
            _turn(language, intents, "Revisa {c1_card_mask}."),
            _turn(language, intents, "Listo, tu guía es {c1_tracking_id}.", reported_done=[0]),
        ]
        scripts = [AgentScript(rounds=rounds, finals=[finals[0]])]
        if address == "new":
            # The turn after the OTP words the plan; the address turn itself is code-only.
            scripts.append(AgentScript(rounds=[], finals=[finals[1]]))
        scripts.append(AgentScript(rounds=[], finals=[finals[2]]))
        llm = ScriptedLLM({"agent": scripts})
        session = make_session(customer, fakebank_dir, llm, otp_code=_OTP, write_audit=True)
        session.overlay.blocked.add(card_id)
        sent_texts = _spy_unmask(monkeypatch)

        if address == "on_file":
            await run_recorded_turn(session, monkeypatch, "quiero una tarjeta nueva")
            assert "otp_required" not in await _ui_kinds(session)
            _, ui = await _open_plan(session)
            assert [s.tool for s in ui[0].payload.steps] == ["cards.order_replacement"]
            facts = {f.key: f.value for f in ui[0].payload.steps[0].facts}
            assert facts["address_masked"] == "•••, Bogota"
        else:
            await run_recorded_turn(session, monkeypatch, "quero um cartão novo")
            assert await _ui_kinds(session) == ["otp_required"]
            assert session.gate.verify(_OTP) is True
            ask, _ = await run_turn(session.graph, "", config=session.config, resume="step_up")
            assert get_template("address_ask", language) in ask
            reply, _ = await run_turn(
                session.graph, "Rua das Flores 10, Sao Paulo", config=session.config
            )
            assert get_template("agent_plan_ready", language) in reply
            _, ui = await _open_plan(session)
            assert [s.tool for s in ui[0].payload.steps] == ["cards.order_replacement"]

        e3 = await _accept(session, monkeypatch)
        assert [t for t, _ in e3].count("readback") == 1
        tracking_id = session.overlay.replacements[card_id]
        assert tracking_id in sent_texts[-1]
        # R4: the model only ever wrote the placeholder.
        for script in scripts:
            assert all(tracking_id not in getattr(f, "reply", "") for f in script.finals)

    _in_one_loop(run)


@pytest.mark.usefixtures("agent_on")
def test_declined_offer_cancelled_bot_offered(
    monkeypatch: pytest.MonkeyPatch, fakebank_dir: Path
) -> None:
    async def run() -> None:
        rounds = [
            [("card_status", {})],
            [("propose_plan", {"steps": [{"action": "unlock", "card": "c1"}]})],
        ]
        refusal = _turn("es", ["card_unlock"], "Esa tarjeta no se puede desbloquear.")
        llm = ScriptedLLM(
            {
                "agent": [AgentScript(rounds=rounds, finals=[refusal])],
                "nlu": [NLUResult(language="es", intents=["deny"], status="clear")],
            }
        )
        session = make_session("CLI-TFSINGLE0002", fakebank_dir, llm, otp_code=_OTP)
        session.overlay.blocked.add(_SINGLE_CARD)
        sent_texts = _spy_unmask(monkeypatch)

        e1 = await run_recorded_turn(session, monkeypatch, "desbloquea mi tarjeta")
        assert "otp_required" not in await _ui_kinds(session)
        state = (await session.graph.aget_state(session.config)).values
        assert state["pending"] == OFFER_REPLACEMENT_PAUSE
        assert state["bot_offered_flow"] == "replacement"
        offer = get_template("offer_replacement", "es").split("{")[0].strip()
        assert offer in sent_texts[-1]
        statuses = {s["intent"]: s["status"] for s in _one(e1, "reply_sent")["segments"]}
        assert statuses["card_unlock"] == "abstained"

        e2 = await run_recorded_turn(session, monkeypatch, "no")
        assert get_template("replacement_declined", "es") in sent_texts[-1]
        segments = {s["intent"]: s for s in _one(e2, "reply_sent")["segments"]}
        assert segments["replacement_request"]["status"] == "cancelled"
        assert segments["replacement_request"]["bot_offered"] is True

    _in_one_loop(run)
