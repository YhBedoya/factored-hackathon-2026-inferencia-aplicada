"""S1 tests 12, 13 and 14: the multi-card replacement after an agent plan blocks two cards.

Test 12 walks the whole path in PT (offer picker, pick both, address, one confirm card,
two read-backs under one token). Test 13 is R1/R13 at the picker pause: the route gate
rejects ids that were not offered and typed text, and an empty pick declines. Test 14 is
R3: when the second `order_replacement` does not verify, no card is reported as done.
Fake LLM only.
"""

import asyncio
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Literal
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException

import app.api.v1.conversations as conversations_module
from app.api.v1.conversations import PostMessageRequest, post_message
from app.core.actions import ActionResult
from app.domains.cards.schemas import AddressRef, BlockOrigin, BlockReason
from app.domains.conversation.agent.schema import AgentTurn
from app.domains.conversation.graph import CardSelection, ConfirmationDecision, run_turn
from app.domains.conversation.nodes.handoff_summary import HandoffSummaryDraft
from app.domains.conversation.schemas import NLUResult
from app.domains.conversation.store import ConversationRow
from app.domains.conversation.templates import get_template
from app.domains.conversation.tools.fakebank import FakeBankWrites
from app.domains.identity.models import Session as IdentitySession
from tests.conftest import AgentScript, ScriptedLLM, Session, make_session

_CUSTOMER = "CLI-TFMULTI00001"
_CREDIT = "PRD-TFM1CRED0001"
_DEBIT = "PRD-TFM1DEBT0002"
_CLOSED_DEBIT = "PRD-TFM1DEBT0003"
_PLAN = [{"action": "block", "card": "c1"}, {"action": "block", "card": "c2"}]


def _turn(
    language: Literal["es", "pt"], reply: str, reported_done: list[int] | None = None
) -> AgentTurn:
    return AgentTurn(
        language=language,
        intents=["card_block"],
        outcome="answered",
        awaiting_slot=None,
        reported_done=reported_done or [],
        reply=reply,
    )


def _script(
    language: Literal["es", "pt"], *, extra: list[NLUResult | HandoffSummaryDraft]
) -> ScriptedLLM:
    plan_turn = AgentScript(
        rounds=[[("card_status", {})], [("propose_plan", {"steps": _PLAN})]],
        finals=[_turn(language, "...")],
    )
    done_turn = AgentScript(rounds=[], finals=[_turn(language, "...", reported_done=[0, 1])])
    outputs: dict[Any, Any] = {"agent": [plan_turn, done_turn]}
    nlu = [x for x in extra if isinstance(x, NLUResult)]
    summary = [x for x in extra if isinstance(x, HandoffSummaryDraft)]
    if nlu:
        outputs["nlu"] = nlu
    if summary:
        outputs["handoff_summary"] = summary
    return ScriptedLLM(outputs)


async def _to_picker(session: Session, language: Literal["es", "pt"]) -> tuple[str, Any]:
    """Plan to block both cards for good, then Acepto: stops at the `replacement_cards` pause."""
    await run_turn(session.graph, "bloquear", config=session.config)
    values = (await session.graph.aget_state(session.config)).values
    assert [s.tool for s in values["open_question"]["ui"][0].payload.steps] == [
        "cards.block_card"
    ] * 2
    token = values["confirmation_token_id"]
    decision = ConfirmationDecision(token_id=token, decision="confirm")
    return await run_turn(session.graph, "", config=session.config, confirmation=decision)


def test_replace_two_blocked_cards_pt(fakebank_dir: Path, agent_on: None) -> None:
    async def run() -> None:
        affirm = NLUResult(language="pt", intents=["affirm"], status="clear")
        llm = _script("pt", extra=[affirm])
        session = make_session(_CUSTOMER, fakebank_dir, llm, write_audit=True)

        reply, debug = await _to_picker(session, "pt")
        assert reply.endswith(get_template("offer_replacement_multi", "pt"))
        assert debug.pending == "replacement.replacement_cards"
        state = (await session.graph.aget_state(session.config)).values
        pickers = [e for e in state["ui"] if e.kind == "card_picker"]
        assert len(pickers) == 1 and pickers[0].payload.multi is True
        options = pickers[0].payload.options
        assert [o.card_id for o in options] == [_CREDIT, _DEBIT]
        assert all(re.fullmatch(r"\S+ •••• (6475|1203)", o.label) for o in options)
        assert [o.label[-4:] for o in options] == ["6475", "1203"]

        selection = CardSelection(card_ids=[_CREDIT, _DEBIT])
        _, debug = await run_turn(
            session.graph, "", config=session.config, card_selection=selection
        )
        assert debug.pending == "replacement.address_confirm"
        state = (await session.graph.aget_state(session.config)).values
        assert state["replacement_card_ids"] == [_CREDIT, _DEBIT]

        reply, debug = await run_turn(session.graph, "sim", config=session.config)
        assert debug.pending == "replacement.confirmation"
        state = (await session.graph.aget_state(session.config)).values
        confirm = state["ui"][-1]
        assert confirm.kind == "confirm" and confirm.payload.labels == "confirm_cancel"
        assert [s.tool for s in confirm.payload.steps] == ["cards.order_replacement"] * 2
        token = state["confirmation_token_id"]

        before = len(session.audit.events)
        reply, _ = await run_turn(
            session.graph,
            "",
            config=session.config,
            confirmation=ConfirmationDecision(token_id=token, decision="confirm"),
        )
        readbacks = [p for t, p in session.audit.events[before:] if str(t) == "readback"]
        assert len(readbacks) == 2
        # One click on the one confirm card (one token) produced both read-backs.
        assert {p["tool"] for p in readbacks} == {"cards.order_replacement"}
        tracking = re.findall(r"RPL-[0-9A-Z]+", reply)
        assert len(tracking) == 2 and tracking[0] != tracking[1]

    asyncio.run(run())


def test_r1_card_selection_gate(
    fakebank_dir: Path, agent_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    started: list[Any] = []

    async def _fail(*args: Any, **kwargs: Any) -> Any:
        started.append((args, kwargs))
        return uuid4()

    monkeypatch.setattr(conversations_module, "start_turn", _fail)

    async def run() -> None:
        session = make_session(_CUSTOMER, fakebank_dir, _script("es", extra=[]), write_audit=True)
        await _to_picker(session, "es")
        before_state = (await session.graph.aget_state(session.config)).values
        events_before = len(session.audit.events)

        conversation = ConversationRow(
            id=UUID(session.config["configurable"]["thread_id"]),
            customer_id=_CUSTOMER,
            language="es",
            mode="bot",
            status="open",
        )
        identity_session = IdentitySession(
            account_id=uuid4(), role="customer", customer_id=_CUSTOMER, step_up_at=None
        )
        turn_host = SimpleNamespace(graph=session.graph)
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(turn_host=turn_host)))

        async def post(body: PostMessageRequest) -> HTTPException:
            with pytest.raises(HTTPException) as exc:
                await post_message(
                    body=body,
                    request=request,  # type: ignore[arg-type]
                    session=identity_session,
                    conversation=conversation,
                )
            return exc.value

        for ids in ([_CLOSED_DEBIT], [_CREDIT, "PRD-OF-ANOTHER-CUSTOMER"]):
            bad = await post(PostMessageRequest(card_selection=CardSelection(card_ids=ids)))
            assert (bad.status_code, bad.detail) == (409, "selection_invalid")
        typed = await post(PostMessageRequest(text="cualquiera"))
        assert (typed.status_code, typed.detail) == (409, "selection_required")
        assert started == []

        after_state = (await session.graph.aget_state(session.config)).values
        assert after_state["pending"] == before_state["pending"]
        assert after_state["replacement_card_ids"] == before_state["replacement_card_ids"]

        reply, _ = await run_turn(
            session.graph, "", config=session.config, card_selection=CardSelection(card_ids=[])
        )
        assert get_template("replacement_declined_multi", "es") in reply
        final = (await session.graph.aget_state(session.config)).values
        assert final["confirmation_token_id"] is None
        assert final["replacement_card_ids"] is None
        # No plan issued and no write ran after the decline.
        assert not [e for e in session.audit.events[events_before:] if str(e[0]) == "tool_result"]

    asyncio.run(run())


class _UnverifiedSecondReplacement:
    """`BankWriteTools` that delegates to the fake bank, except the second
    `order_replacement` comes back `verified=False` (R3)."""

    def __init__(self) -> None:
        self.inner: FakeBankWrites | None = None
        self.orders = 0

    async def get_block_origin(self, card_id: str) -> BlockOrigin:
        assert self.inner is not None
        return await self.inner.get_block_origin(card_id)

    async def lock_card(self, card_id: str, *, idempotency_key: str) -> ActionResult:
        raise NotImplementedError

    async def unlock_card(self, card_id: str, *, idempotency_key: str) -> ActionResult:
        raise NotImplementedError

    async def block_card(
        self, card_id: str, reason: BlockReason, *, idempotency_key: str
    ) -> ActionResult:
        assert self.inner is not None
        return await self.inner.block_card(card_id, reason, idempotency_key=idempotency_key)

    async def order_replacement(
        self, card_id: str, address_ref: AddressRef, *, idempotency_key: str
    ) -> ActionResult:
        assert self.inner is not None
        self.orders += 1
        result = await self.inner.order_replacement(
            card_id, address_ref, idempotency_key=idempotency_key
        )
        if self.orders == 2:
            return result.model_copy(update={"verified": False})
        return result


def test_r3_unverified_second_replacement_hands_off(fakebank_dir: Path, agent_on: None) -> None:
    async def run() -> None:
        affirm = NLUResult(language="es", intents=["affirm"], status="clear")
        draft = HandoffSummaryDraft(request="Reemplazo sin verificar en {queue_label}.")
        llm = _script("es", extra=[affirm, draft])
        writes = _UnverifiedSecondReplacement()
        session = make_session(_CUSTOMER, fakebank_dir, llm, raw_writes=writes, write_audit=True)
        ctx = session.config["configurable"]["session"]
        writes.inner = FakeBankWrites(ctx, fakebank_dir, session.overlay)

        await _to_picker(session, "es")
        selection = CardSelection(card_ids=[_CREDIT, _DEBIT])
        await run_turn(session.graph, "", config=session.config, card_selection=selection)
        await run_turn(session.graph, "si", config=session.config)
        state = (await session.graph.aget_state(session.config)).values
        token = state["confirmation_token_id"]

        reply, debug = await run_turn(
            session.graph,
            "",
            config=session.config,
            confirmation=ConfirmationDecision(token_id=token, decision="confirm"),
        )
        assert writes.orders == 2
        assert "RPL-" not in reply and "Listo" not in reply
        packet = session.handoff_tools.created[-1]
        assert packet.reason == "action_unverified"
        assert debug.pending is None

    asyncio.run(run())
