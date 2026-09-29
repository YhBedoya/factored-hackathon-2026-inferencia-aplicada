"""B5 `card_block` happy paths and the deny cancellation (D11, D14, D17).

See the spec's Test list rows for `test_block_flows.py`. Fake LLM only,
`make_session` (T10) wires `ConfirmedWriteTools` over the test fixture, and
every turn is driven with `asyncio.run` (this card's convention: no
pytest-asyncio).
"""

import asyncio
import re
from pathlib import Path

from app.domains.conversation.graph import ConfirmationDecision, run_turn
from app.domains.conversation.nodes.handoff_summary import HandoffSummaryDraft
from app.domains.conversation.schemas import NLUResult, NLUSlots
from app.domains.conversation.templates import get_template
from tests.conftest import ScriptedLLM, make_session


def test_es_lock_clarify_confirm_readback(fakebank_dir: Path) -> None:
    """A hint resolves the card at once; `block_kind` is missing, so the flow
    clarifies lock-vs-block before it plans anything (step 5a)."""

    async def run() -> None:
        llm = ScriptedLLM(
            {
                "nlu": [
                    NLUResult(
                        language="es",
                        intents=["card_block"],
                        status="clear",
                        slots=NLUSlots(card_hint="credit"),
                    ),
                    NLUResult(
                        language="es",
                        intents=[],
                        status="clear",
                        slots=NLUSlots(block_kind="temporary_lock"),
                    ),
                    NLUResult(language="es", intents=["affirm"], status="clear"),
                ]
            }
        )
        session = make_session("CLI-TFMULTI00001", fakebank_dir, llm)

        reply1, debug1 = await run_turn(
            session.graph, "bloquea mi tarjeta de credito", config=session.config
        )
        assert reply1 == get_template("clarify_lock_vs_block", "es")
        assert debug1.pending == "card_block.block_kind"
        assert debug1.ui == ["quick_replies"]

        state1 = await session.graph.aget_state(session.config)
        quick_replies = state1.values["ui"][0]
        assert quick_replies.payload.slot == "block_kind"
        labels = [option.label for option in quick_replies.payload.options]
        assert len(labels) == 2
        assert not any("cancel" in label.lower() for label in labels)

        reply2, debug2 = await run_turn(session.graph, labels[0], config=session.config)
        assert debug2.pending == "card_block.confirmation"
        assert debug2.ui == ["confirm"]
        assert "6475" in reply2

        reply3, debug3 = await run_turn(session.graph, "si", config=session.config)
        assert debug3.pending is None
        assert re.search(r"quedó bloqueada temporalmente a las \d{2}:\d{2}\.", reply3)
        assert "PRD-TFM1CRED0001" in session.overlay.locked

    asyncio.run(run())


def test_pt_block_by_button_offers_replacement(fakebank_dir: Path) -> None:
    """The single-card customer needs no clarification; a verified permanent
    block offers a replacement, confirmed with the button equivalent (D14)."""

    async def run() -> None:
        llm = ScriptedLLM(
            {
                "nlu": [
                    NLUResult(
                        language="pt",
                        intents=["card_block"],
                        status="clear",
                        slots=NLUSlots(block_kind="permanent_block"),
                    )
                ]
            }
        )
        session = make_session("CLI-TFSINGLE0002", fakebank_dir, llm)

        _reply1, debug1 = await run_turn(
            session.graph, "perdi meu cartao, quero bloquear para sempre", config=session.config
        )
        assert debug1.pending == "card_block.confirmation"
        assert debug1.ui == ["confirm"]

        state = await session.graph.aget_state(session.config)
        token_id = state.values["confirmation_token_id"]
        assert isinstance(token_id, str)

        reply2, debug2 = await run_turn(
            session.graph,
            "",
            config=session.config,
            confirmation=ConfirmationDecision(token_id=token_id, decision="confirm"),
        )
        assert "bloqueado de forma permanente" in reply2
        assert "2222" in reply2
        assert reply2.endswith("Quer que eu peça um cartão novo para substituir o final 2222?")
        assert debug2.pending == "replacement.offer_replacement"
        assert "PRD-TFS2CRED0001" in session.overlay.blocked
        # Only the button/step-up resume skips `understand`; this one still did.
        assert sum(1 for call in llm.calls if call.step == "nlu") == 1

    asyncio.run(run())


def test_es_deny_cancels_plan(fakebank_dir: Path) -> None:
    """A typed "no" cancels the plan; nothing is written (D14)."""

    async def run() -> None:
        llm = ScriptedLLM(
            {
                "nlu": [
                    NLUResult(
                        language="es",
                        intents=["card_block"],
                        status="clear",
                        slots=NLUSlots(block_kind="temporary_lock"),
                    ),
                    NLUResult(language="es", intents=["deny"], status="clear"),
                ]
            }
        )
        session = make_session("CLI-TFSINGLE0002", fakebank_dir, llm)

        _reply1, debug1 = await run_turn(session.graph, "bloquea mi tarjeta", config=session.config)
        assert debug1.pending == "card_block.confirmation"

        reply2, debug2 = await run_turn(session.graph, "no", config=session.config)
        assert reply2 == get_template("action_cancelled", "es")
        assert debug2.pending is None
        assert session.overlay.locked == set()
        assert session.overlay.blocked == set()

    asyncio.run(run())


def test_pt_bank_side_unlock_hands_off(fakebank_dir: Path) -> None:
    """`card_unlock` on a bank-side block hands off to the reason's queue, with
    no OTP and no write (D8, D9, step 5d)."""

    async def run() -> None:
        llm = ScriptedLLM(
            {
                "nlu": [
                    NLUResult(language="pt", intents=["card_unlock"], status="clear"),
                ],
                "handoff_summary": [
                    HandoffSummaryDraft(request="Bloqueio do banco em {queue_label}.")
                ],
            }
        )
        past_due_session = make_session("CLI-TFPASTD00005", fakebank_dir, llm)
        reply1, debug1 = await run_turn(
            past_due_session.graph, "quero desbloquear meu cartao", config=past_due_session.config
        )
        assert "Cobrança" in reply1
        packet1 = past_due_session.handoff_tools.created[-1]
        assert (packet1.queue, packet1.reason) == ("cobranza", "bank_side_block")
        assert debug1.pending is None
        assert debug1.ui == ["handoff_banner"]
        assert past_due_session.overlay.locked == set()
        assert past_due_session.overlay.blocked == set()

        llm2 = ScriptedLLM(
            {
                "nlu": [
                    NLUResult(language="pt", intents=["card_unlock"], status="clear"),
                ],
                "handoff_summary": [
                    HandoffSummaryDraft(request="Bloqueio do banco em {queue_label}.")
                ],
            }
        )
        blocked_session = make_session("CLI-TFBLOCKD0003", fakebank_dir, llm2)
        reply2, debug2 = await run_turn(
            blocked_session.graph, "quero desbloquear meu cartao", config=blocked_session.config
        )
        assert "Fraudes" in reply2
        packet2 = blocked_session.handoff_tools.created[-1]
        assert (packet2.queue, packet2.reason) == ("fraudes", "bank_side_block")
        assert debug2.pending is None
        assert debug2.ui == ["handoff_banner"]
        assert blocked_session.overlay.locked == set()
        assert blocked_session.overlay.blocked == set()

    asyncio.run(run())


def test_es_lost_card_block_replacement_tracking(fakebank_dir: Path) -> None:
    """A lost-card report blocks the card, offers a replacement, and an
    on-file address needs no OTP before the tracking id comes back (D13,
    step 5c)."""

    async def run() -> None:
        llm = ScriptedLLM(
            {
                "nlu": [
                    NLUResult(
                        language="es",
                        intents=["card_block"],
                        status="clear",
                        slots=NLUSlots(block_kind="permanent_block"),
                    ),
                    NLUResult(language="es", intents=["affirm"], status="clear"),
                    NLUResult(language="es", intents=["affirm"], status="clear"),
                    NLUResult(language="es", intents=["affirm"], status="clear"),
                    NLUResult(language="es", intents=["affirm"], status="clear"),
                ]
            }
        )
        session = make_session("CLI-TFSINGLE0002", fakebank_dir, llm)

        _reply1, debug1 = await run_turn(
            session.graph, "la perdí, bloquéala para siempre", config=session.config
        )
        assert debug1.pending == "card_block.confirmation"

        reply2, debug2 = await run_turn(session.graph, "sí", config=session.config)
        assert debug2.pending == "replacement.offer_replacement"

        reply3, debug3 = await run_turn(session.graph, "sí", config=session.config)
        assert debug3.pending == "replacement.address_confirm"

        reply4, debug4 = await run_turn(session.graph, "sí", config=session.config)
        assert debug4.pending == "replacement.confirmation"

        reply5, debug5 = await run_turn(session.graph, "sí", config=session.config)
        assert debug5.pending is None
        assert re.search(r"RPL-[0-9A-F]+", reply5)

        otp_text = get_template("otp_required", "es")
        assert otp_text not in (reply2, reply3, reply4, reply5)

    asyncio.run(run())


def test_pt_new_address_needs_otp_and_is_vaulted(fakebank_dir: Path) -> None:
    """A new delivery address needs step-up first; the raw text never reaches
    the LLM, the facts, the ui payload or the plan's args (D4, D13, R5)."""

    async def run() -> None:
        raw_address = "Rua Nova 123, apto 4, São Paulo"
        llm = ScriptedLLM(
            {
                "nlu": [
                    NLUResult(language="pt", intents=["replacement_request"], status="clear"),
                    NLUResult(language="pt", intents=["deny"], status="clear"),
                    NLUResult(language="pt", intents=["affirm"], status="clear"),
                ]
            }
        )
        session = make_session("CLI-TFSINGLE0002", fakebank_dir, llm, otp_code="1234")
        session.overlay.blocked.add("PRD-TFS2CRED0001")

        _reply1, debug1 = await run_turn(
            session.graph, "quero um cartão novo", config=session.config
        )
        assert debug1.pending == "replacement.address_confirm"

        reply2, debug2 = await run_turn(session.graph, "não", config=session.config)
        assert reply2 == get_template("otp_required", "pt")
        assert debug2.pending == "replacement.otp"

        assert session.gate.verify("1234") is True
        reply3, debug3 = await run_turn(session.graph, "", config=session.config, resume="step_up")
        assert reply3 == get_template("address_ask", "pt")
        assert debug3.pending == "replacement.address"

        nlu_calls_before = sum(1 for call in llm.calls if call.step == "nlu")
        reply4, debug4 = await run_turn(session.graph, raw_address, config=session.config)
        assert sum(1 for call in llm.calls if call.step == "nlu") == nlu_calls_before
        assert debug4.pending == "replacement.confirmation"
        assert raw_address not in reply4

        for call in llm.calls:
            assert raw_address not in call.user

        final_state = await session.graph.aget_state(session.config)
        assert raw_address not in str(final_state.values.get("facts"))
        assert raw_address not in str(final_state.values.get("ui"))

        token_id = final_state.values["confirmation_token_id"]
        plan = session.store._plans[token_id]  # test-only: prove the vaulted ref, not the raw text
        assert plan.steps[0].args["address_ref"] == "⟨ADDR_1⟩"
        assert raw_address not in str(plan.steps[0].args)

        reply5, debug5 = await run_turn(session.graph, "sim", config=session.config)
        assert debug5.pending is None
        assert re.search(r"RPL-[0-9A-F]+", reply5)

    asyncio.run(run())


def test_es_unlock_own_lock_needs_otp(fakebank_dir: Path) -> None:
    """A lock made in this session needs step-up before `card_unlock` can even
    issue a plan (D1, D12, step 5b). `understand` never runs on a resume or a
    button-confirm turn."""

    async def run() -> None:
        llm = ScriptedLLM(
            {
                "nlu": [
                    NLUResult(language="es", intents=["card_unlock"], status="clear"),
                ]
            }
        )
        session = make_session("CLI-TFSINGLE0002", fakebank_dir, llm, otp_code="1234")
        session.overlay.locked.add("PRD-TFS2CRED0001")

        reply1, debug1 = await run_turn(
            session.graph, "quiero desbloquear mi tarjeta", config=session.config
        )
        assert reply1 == get_template("otp_required", "es")
        assert debug1.pending == "card_unlock.otp"

        # Still-invalid gate: the resume executes nothing, same pause again.
        reply2, debug2 = await run_turn(session.graph, "", config=session.config, resume="step_up")
        assert reply2 == get_template("otp_required", "es")
        assert debug2.pending == "card_unlock.otp"

        assert session.gate.verify("1234") is True

        reply3, debug3 = await run_turn(session.graph, "", config=session.config, resume="step_up")
        assert debug3.pending == "card_unlock.confirmation"
        assert "2222" in reply3

        state = await session.graph.aget_state(session.config)
        token_id = state.values["confirmation_token_id"]
        assert isinstance(token_id, str)

        reply4, debug4 = await run_turn(
            session.graph,
            "",
            config=session.config,
            confirmation=ConfirmationDecision(token_id=token_id, decision="confirm"),
        )
        assert debug4.pending is None
        assert re.search(r"quedó desbloqueada a las \d{2}:\d{2}\.", reply4)
        assert "PRD-TFS2CRED0001" not in session.overlay.locked

        assert sum(1 for call in llm.calls if call.step == "nlu") == 1

    asyncio.run(run())


def test_which_card_question_names_the_action(fakebank_dir: Path) -> None:
    """With several cards and no hint, the question names the action the
    customer asked for (ES block, PT unlock), from a fixed template (D12)."""

    async def run() -> None:
        llm = ScriptedLLM(
            {
                "nlu": [
                    NLUResult(language="es", intents=["card_block"], status="clear"),
                    NLUResult(language="pt", intents=["card_unlock"], status="clear"),
                ]
            }
        )
        session = make_session("CLI-TFMULTI00001", fakebank_dir, llm)

        reply1, debug1 = await run_turn(session.graph, "quiero bloquear", config=session.config)
        assert reply1.startswith("¿Cuál tarjeta quieres bloquear?\n")
        assert "6475" in reply1
        assert debug1.pending == "card_block.card_hint"

        reply2, debug2 = await run_turn(
            session.graph, "quero desbloquear meu cartão", config=session.config
        )
        assert reply2.startswith("Qual cartão você quer desbloquear?\n")
        assert debug2.pending == "card_unlock.card_hint"
        assert all(call.step != "compose" for call in llm.calls)

    asyncio.run(run())
