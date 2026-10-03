"""S1 tests 9, 10 and 11: the block conversations in PT and ES, and a passed turn that runs
the pipeline while later turns of an open flow skip the agent."""

import asyncio
from pathlib import Path
from typing import Any, Literal

import pytest

from app.core.db import get_engine
from app.domains.conversation.agent.schema import AgentTurn
from app.domains.conversation.flows.actions import OFFER_REPLACEMENT_PAUSE
from app.domains.conversation.graph import ConfirmationDecision, run_turn
from app.domains.conversation.nodes.next_intent import finish
from app.domains.conversation.schemas import NLUResult
from app.domains.safety.vault import InMemoryPiiVault
from tests.conftest import AgentScript, ScriptedLLM, Session, make_session, run_recorded_turn

_Events = list[tuple[str, dict[str, Any]]]


def _turn(
    language: Literal["es", "pt"],
    intents: list[str],
    reply: str,
    *,
    outcome: Literal["answered", "asked"] = "answered",
    awaiting_slot: str | None = None,
    reported_done: list[int] | None = None,
) -> AgentTurn:
    return AgentTurn(
        language=language,
        intents=intents,
        outcome=outcome,
        awaiting_slot=awaiting_slot,
        reported_done=reported_done or [],
        reply=reply,
    )


def _one(events: _Events, kind: str) -> dict[str, Any]:
    return next(p for t, p in events if t == kind)


async def _open_plan(session: Session) -> Any:
    values = (await session.graph.aget_state(session.config)).values
    return values["confirmation_token_id"], values["open_question"]["ui"]


@pytest.mark.usefixtures("agent_on")
def test_pass_to_flow_keeps_later_turns_on_pipeline(fakebank_dir: Path) -> None:
    async def run() -> None:
        llm = ScriptedLLM(
            {
                "agent": [AgentScript(rounds=[[("pass_to_flow", {})]], finals=[])],
                "nlu": [
                    # A flow that stays open on a question (`block_kind`); an unlock on
                    # this customer's one unlocked card would end at the closing instead.
                    NLUResult(
                        language="es",
                        intents=["card_block"],
                        status="ambiguous",
                        clarification="lock_vs_block",
                    ),
                    NLUResult(language="es", intents=[], status="clear"),
                ],
            }
        )
        session = make_session("CLI-TFSINGLE0002", fakebank_dir, llm)

        _, debug1 = await run_turn(session.graph, "bloquea mi tarjeta", config=session.config)
        assert debug1.route == "card_block"
        assert debug1.pending == "card_block.block_kind"
        assert [c.step for c in llm.calls].count("agent") == 1

        _, debug2 = await run_turn(session.graph, "mmm", config=session.config)
        assert debug2.route == "card_block"
        assert [c.step for c in llm.calls].count("agent") == 1

    asyncio.run(run())


@pytest.mark.usefixtures("agent_on")
def test_block_all_cards_pt(monkeypatch: pytest.MonkeyPatch, fakebank_dir: Path) -> None:
    async def run() -> None:
        steps = [{"action": "lock", "card": "c1"}, {"action": "lock", "card": "c2"}]
        llm = ScriptedLLM(
            {
                "agent": [
                    AgentScript(
                        rounds=[],
                        finals=[
                            _turn(
                                "pt",
                                ["card_block"],
                                "Quer um bloqueio temporário ou por perda ou roubo?",
                                outcome="asked",
                                awaiting_slot="block_kind",
                            )
                        ],
                    ),
                    AgentScript(
                        rounds=[[("card_status", {})], [("propose_plan", {"steps": steps})]],
                        finals=[_turn("pt", ["card_block"], "Confirme no cartão abaixo.")],
                    ),
                    AgentScript(
                        rounds=[],
                        finals=[_turn("pt", ["card_block"], "Pronto.", reported_done=[0, 1])],
                    ),
                ]
            }
        )
        session = make_session("CLI-TFMULTI00001", fakebank_dir, llm, write_audit=True)

        e1 = await run_recorded_turn(session, monkeypatch, "Quero bloquear meus cartões")
        e2 = await run_recorded_turn(session, monkeypatch, "Temporário, todos")
        token, ui = await _open_plan(session)
        assert len(ui) == 1 and ui[0].kind == "confirm"
        assert [s.tool for s in ui[0].payload.steps] == ["cards.lock_card"] * 2
        assert ui[0].payload.labels == "accept_decline"
        assert not session.overlay.locked

        decision = ConfirmationDecision(token_id=token, decision="confirm")
        e3 = await run_recorded_turn(session, monkeypatch, "", confirmation=decision)

        assert len([1 for t, _ in e3 if t == "readback"]) == 2
        assert len(session.overlay.locked) == 2
        assert [_one(e, "nlu_result")["source"] for e in (e1, e2)] == ["agent", "agent"]
        sent = [_one(e, "reply_sent") for e in (e1, e2, e3)]
        assert [p["path"] for p in sent] == ["agent", "agent", "agent"]
        assert [p["segments"][0]["status"] for p in sent] == ["awaiting", "awaiting", "resolved"]
        assert [p["segments"][0].get("awaiting_slot") for p in sent] == [
            "block_kind",
            "confirmation",
            None,
        ]

    async def in_one_loop() -> None:
        try:
            await run()
        finally:
            await get_engine().dispose()

    asyncio.run(in_one_loop())


@pytest.mark.usefixtures("agent_on")
def test_block_and_balance_one_message_es(
    monkeypatch: pytest.MonkeyPatch, fakebank_dir: Path
) -> None:
    async def run() -> None:
        reply = "Propongo bloquear {c1_card_mask}. En {c2_card_mask} tienes {c2_available_balance}."
        rounds = [
            [("card_status", {})],
            [
                ("debit_balance", {"card": "c2"}),
                ("propose_plan", {"steps": [{"action": "block", "card": "c1"}]}),
            ],
        ]
        turn = _turn("es", ["card_block", "balance_due"], reply)
        # Cardy adds its own bullets before the mask and its own closing question.
        done = _turn(
            "es",
            ["card_block"],
            "Listo, la tarjeta •••• {c1_card_mask} quedó bloqueada. ¿Te ayudo con algo más?",
            reported_done=[0],
        )
        llm = ScriptedLLM(
            {
                "agent": [
                    AgentScript(rounds=rounds, finals=[turn]),
                    AgentScript(rounds=[], finals=[done]),
                ]
            }
        )
        session = make_session("CLI-TFMULTI00001", fakebank_dir, llm, write_audit=True)
        sent_texts: list[str] = []
        unmask = InMemoryPiiVault.unmask

        async def _spy(self: InMemoryPiiVault, text: str) -> str:
            # The runner unmasks exactly the reply it sends; record it here.
            sent_texts.append(text)
            return await unmask(self, text)

        monkeypatch.setattr(InMemoryPiiVault, "unmask", _spy)

        events = await run_recorded_turn(
            session, monkeypatch, "Bloquea la de crédito y dime cuánto debo en la otra"
        )

        _, ui = await _open_plan(session)
        assert len(ui) == 1 and len(ui[0].payload.steps) == 1
        sent = _one(events, "reply_sent")
        assert len(sent["segments"]) == 2
        assert "US$850.00" in "".join(sent["fact_values"])
        assert not session.overlay.locked

        # Acepto on a permanent block: Cardy's result, then the code-written one-card offer.
        token, _ = await _open_plan(session)
        decision = ConfirmationDecision(token_id=token, decision="confirm")
        clicked = await run_recorded_turn(session, monkeypatch, "", confirmation=decision)
        assert len([1 for t, _ in clicked if t == "readback"]) == 1
        text = sent_texts[-1]
        state = (await session.graph.aget_state(session.config)).values
        assert state["pending"] == OFFER_REPLACEMENT_PAUSE
        assert state["selected_card_id"] == "PRD-TFM1CRED0001"
        assert state["replacement_card_ids"] is None
        assert not any(e.kind == "card_picker" for e in state.get("ui") or [])
        assert text.index("bloqueada") < text.index("reemplazar")
        # R4: one mask, never "•••• •••• NNNN"; and one closing question, the offer's.
        assert "•••• ••••" not in text
        assert text.count("?") == 1

    async def in_one_loop() -> None:
        try:
            await run()
        finally:
            await get_engine().dispose()

    asyncio.run(in_one_loop())


@pytest.mark.usefixtures("agent_on")
def test_lock_done_reply_has_one_closing_question_es(
    monkeypatch: pytest.MonkeyPatch, fakebank_dir: Path
) -> None:
    async def run() -> None:
        rounds = [
            [("card_status", {})],
            [("propose_plan", {"steps": [{"action": "lock", "card": "c1"}]})],
        ]
        proposal = _turn(
            "es", ["card_block"], "Propongo bloquear {c1_card_mask} de forma temporal."
        )
        # No replacement offer follows a lock, so code's own closing is the one that stays.
        done = _turn(
            "es",
            ["card_block"],
            "Listo, quedó bloqueada. ¿Te ayudo con algo más?",
            reported_done=[0],
        )
        llm = ScriptedLLM(
            {
                "agent": [
                    AgentScript(rounds=rounds, finals=[proposal]),
                    AgentScript(rounds=[], finals=[done]),
                ]
            }
        )
        session = make_session("CLI-TFMULTI00001", fakebank_dir, llm, write_audit=True)
        sent_texts: list[str] = []
        unmask = InMemoryPiiVault.unmask

        async def _spy(self: InMemoryPiiVault, text: str) -> str:
            sent_texts.append(text)
            return await unmask(self, text)

        monkeypatch.setattr(InMemoryPiiVault, "unmask", _spy)
        await run_recorded_turn(session, monkeypatch, "Bloquea temporalmente mi tarjeta de crédito")
        token, _ = await _open_plan(session)
        decision = ConfirmationDecision(token_id=token, decision="confirm")
        await run_recorded_turn(session, monkeypatch, "", confirmation=decision)
        assert sent_texts[-1].count("?") == 1

    async def in_one_loop() -> None:
        try:
            await run()
        finally:
            await get_engine().dispose()

    asyncio.run(in_one_loop())


def test_finish_keeps_trailing_question_when_agent_did_not_reply() -> None:
    # Flag off: a pipeline flow's last segment is left alone when the closing is appended.
    class _Done:
        verified = True

    state: Any = {
        "language": "es",
        "segments": ["Listo. ¿Quieres algo más?"],
        "actions": [_Done()],
        "actions_at_turn_start": 0,
    }
    reply = finish(state)["reply"]
    assert reply.startswith("Listo. ¿Quieres algo más?\n\n")
    assert reply.count("?") == 2
