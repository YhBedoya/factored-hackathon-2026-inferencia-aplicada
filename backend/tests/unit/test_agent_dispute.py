"""S3 tests 1, 2, 4, 5 and 6: the unrecognised-charge conversation through the agent (the pick
gate, the claim check, the single-charge claim, the block-and-claim plan, and the handoff
packet against the flow's). Fake LLM and fake bank only."""

import asyncio
import re
from collections.abc import Awaitable, Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Literal, cast
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException

import app.api.v1.conversations as conversations_module
from app.api.v1.conversations import PostMessageRequest, post_message
from app.core.config import get_settings
from app.core.db import get_engine
from app.core.errors import PolicyDenied
from app.domains.conversation import runner
from app.domains.conversation.agent.plan import PlanBox, ProposeArgs, propose_plan
from app.domains.conversation.agent.reads import read_tools
from app.domains.conversation.agent.refs import TurnRefs
from app.domains.conversation.agent.schema import AgentTurn
from app.domains.conversation.graph import (
    ConfirmationDecision,
    GraphState,
    TxSelection,
    run_turn,
)
from app.domains.conversation.nodes.handoff_summary import HandoffSummaryDraft
from app.domains.conversation.schemas import NLUResult
from app.domains.conversation.store import ConversationRow
from app.domains.conversation.templates import Language, get_template
from app.domains.conversation.tools.executor import ConfirmedWriteTools
from app.domains.conversation.tools.fakebank import FakeBankWrites
from app.domains.handoff.schemas import HandoffPacket
from app.domains.identity.models import Session as IdentitySession
from app.domains.identity.step_up_fake import FakeStepUpGate
from app.domains.policy.confirmation import PlanStep
from app.domains.policy.registry import get_policies
from app.domains.policy.tools_policy import has_preconditions, step_up_rule, tool_allowed
from app.domains.safety.vault import InMemoryPiiVault
from tests.conftest import AgentScript, ScriptedLLM, Session, make_session, run_recorded_turn

_Events = list[tuple[str, dict[str, Any]]]
_CUSTOMER = "CLI-TFSINGLE0002"
_CARD_ID = "PRD-TFS2CRED0001"
_TXN01 = "TRX-TFS2CRED0001TXN01"  # Approved, low fraud_score
_TXN02 = "TRX-TFS2CRED0001TXN02"  # low fraud_score
_TXN03 = "TRX-TFS2CRED0001TXN03"  # Pending, fraud_score 45.00
_FOREIGN_TX = "TRX-TFM1CRED0001TXN01"  # CLI-TFMULTI00001's, never this customer's
_SUMMARY = HandoffSummaryDraft(
    request="{tx_count} cargos no reconocidos, cola {queue_label}.",
    asked="Pidió ayuda.",
    did="Nada.",
    unfinished="Todo.",
)
_OPENING = {
    "es": "no reconozco un cargo en mi tarjeta",
    "pt": "não reconheço uma compra no meu cartão",
}


def _turn(
    language: Language,
    reply: str,
    *,
    asked: str | None = None,
    reported_done: list[int] | None = None,
) -> AgentTurn:
    lang: Literal["es", "pt"] = language
    return AgentTurn(
        language=lang,
        intents=["unrecognized_charge"],
        outcome="asked" if asked else "answered",
        awaiting_slot=cast(Any, asked),
        reported_done=reported_done or [],
        reply=reply,
    )


def _claim(charges: list[str], answers: dict[str, str] | None = None) -> dict[str, Any]:
    step: dict[str, Any] = {"action": "claim", "charges": charges}
    if answers is not None:
        step["answers"] = answers
    return {"steps": [step]}


_OPEN_ROUNDS: list[list[tuple[str, dict[str, Any]]]] = [
    [("card_status", {})],
    [("dispute_candidates", {"card": "c1"})],
]


def _in_one_loop(run: Callable[[], Awaitable[None]]) -> None:
    async def wrapped() -> None:
        try:
            await run()
        finally:
            await get_engine().dispose()

    asyncio.run(wrapped())


def _spy_unmask(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """The runner unmasks exactly the reply it sends; record each one."""
    sent: list[str] = []
    unmask = InMemoryPiiVault.unmask

    async def _spy(self: InMemoryPiiVault, text: str) -> str:
        sent.append(text)
        return await unmask(self, text)

    monkeypatch.setattr(InMemoryPiiVault, "unmask", _spy)
    return sent


async def _state(session: Session) -> dict[str, Any]:
    return dict((await session.graph.aget_state(session.config)).values)


async def _accept(session: Session, monkeypatch: pytest.MonkeyPatch) -> _Events:
    token = (await _state(session))["confirmation_token_id"]
    decision = ConfirmationDecision(token_id=token, decision="confirm")
    return await run_recorded_turn(session, monkeypatch, "", confirmation=decision)


def _one(events: _Events, kind: str) -> dict[str, Any]:
    return next(p for t, p in events if t == kind)


async def _picked_state(
    session: Session, picked: list[str]
) -> tuple[GraphState, TurnRefs, dict[str, str]]:
    """A later turn of a dispute: the charges were read this session, `picked` are the
    customer's picks and live in `state`. Returns the state, the refs and `tx_id -> handle`."""
    state = cast(GraphState, {"language": "es", "country": "CO"})
    refs = TurnRefs("es", "CO")
    tools = {t.name: t for t in read_tools(state, session.config, refs)}
    await tools["card_status"].handler(tools["card_status"].args_schema())
    await tools["dispute_candidates"].handler(
        tools["dispute_candidates"].args_schema.model_validate({"card": "c1"})
    )
    dispute = {**refs.graph_update.pop("dispute"), "picked_tx_ids": picked}
    state = cast(GraphState, {**state, "dispute": dispute})
    handles = {tx_id: f"t{i}" for i in range(1, 10) if (tx_id := refs.tx_id(f"t{i}")) is not None}
    return state, refs, handles


def _assert_nothing_issued(session: Session, box: PlanBox) -> None:
    assert session.store._plans == {}
    assert box.update() == {}
    assert session.overlay.blocked == set()
    assert not any(t == "confirmation_issued" for t, _ in session.audit.events)
    assert not any(t == "tool_result" for t, _ in session.audit.events)


@pytest.mark.usefixtures("agent_on")
def test_r1_foreign_or_unpicked_charge_refused(
    monkeypatch: pytest.MonkeyPatch, fakebank_dir: Path
) -> None:
    calls: list[tuple[Any, ...]] = []

    async def _recorder(*args: Any, **kwargs: Any) -> Any:
        calls.append((args, kwargs))
        return uuid4()

    async def _no_caps(*_: Any, **__: Any) -> None:
        return None

    monkeypatch.setattr(conversations_module, "start_turn", _recorder)
    monkeypatch.setattr(conversations_module, "_check_turn_caps", _no_caps)
    monkeypatch.setattr(conversations_module, "_count_turn", _no_caps)

    async def run() -> None:
        # (a) the pick gate at the agent's dispute pause.
        open_turn = _turn("es", "Elige los cargos.", asked="dispute_question")
        llm = ScriptedLLM({"agent": [AgentScript(rounds=_OPEN_ROUNDS, finals=[open_turn])]})
        session = make_session(_CUSTOMER, fakebank_dir, llm, write_audit=True)
        await run_recorded_turn(session, monkeypatch, _OPENING["es"])
        assert (await _state(session))["pending"]["node"] == "dispute_pick"

        conversation = ConversationRow(
            id=UUID(session.config["configurable"]["thread_id"]),
            customer_id=_CUSTOMER,
            language="es",
            mode="bot",
            status="open",
        )
        identity = IdentitySession(
            account_id=uuid4(), role="customer", customer_id=_CUSTOMER, step_up_at=None
        )
        app_state = SimpleNamespace(turn_host=SimpleNamespace(graph=session.graph))
        request = SimpleNamespace(app=SimpleNamespace(state=app_state))

        async def post(tx_ids: list[str]) -> Any:
            return await post_message(
                body=PostMessageRequest(selection=TxSelection(tx_ids=tx_ids)),
                request=request,  # type: ignore[arg-type]
                session=identity,
                conversation=conversation,
            )

        with pytest.raises(HTTPException) as foreign:
            await post([_FOREIGN_TX])
        assert foreign.value.status_code == 409
        assert foreign.value.detail == "selection_invalid"
        assert calls == []
        await post([_TXN01])  # the control: an offered id reaches the turn
        assert len(calls) == 1

        # (b) and (c): the claim check, called directly. Nothing is issued or written.
        state, refs, handle_of = await _picked_state(session, [_TXN01])
        for charges in ([_FOREIGN_TX], [handle_of[_TXN02]]):
            box = PlanBox()
            result = await propose_plan(
                ProposeArgs.model_validate(_claim(charges)),
                state=state,
                config=session.config,
                refs=refs,
                box=box,
            )
            expected = "unknown_reference" if charges == [_FOREIGN_TX] else "not_picked"
            assert result == f"rejected (claim: {expected})"
            _assert_nothing_issued(session, box)

    _in_one_loop(run)


@pytest.mark.usefixtures("agent_on")
def test_r8_claim_gated_by_policy_preconditions(fakebank_dir: Path) -> None:
    async def run() -> None:
        session = make_session(_CUSTOMER, fakebank_dir, ScriptedLLM({}), write_audit=True)
        state, refs, handle_of = await _picked_state(session, [_TXN01])
        low = handle_of[_TXN01]

        async def propose(answers: dict[str, str]) -> tuple[str, PlanBox]:
            box = PlanBox()
            result = await propose_plan(
                ProposeArgs.model_validate(_claim([low], answers)),
                state=state,
                config=session.config,
                refs=refs,
                box=box,
            )
            return result, box

        for answers, missing in (
            ({}, "card_in_possession"),
            ({"card_in_possession": "yes"}, "contacted_merchant"),
        ):
            result, box = await propose(answers)
            assert result == f"rejected (claim: missing_answer:{missing})"
            _assert_nothing_issued(session, box)

        # A blocked card and the score-45 charge: the claim stands alone, no block step.
        session.overlay.blocked.add(_CARD_ID)
        state, refs, handle_of = await _picked_state(session, [_TXN03])
        box = PlanBox()
        result = await propose_plan(
            ProposeArgs.model_validate(_claim([handle_of[_TXN03]])),
            state=state,
            config=session.config,
            refs=refs,
            box=box,
        )
        assert result == "accepted"
        event = box.event
        assert event is not None
        assert [s.tool for s in event.payload.steps] == ["disputes.create_claim"]

        # R8: with the `preconditions` block gone from the policy, the agent path denies it.
        tools = get_policies().tools
        bare = tools.model_copy(
            update={
                "tools": {
                    **tools.tools,
                    "disputes.create_claim": tools.tools["disputes.create_claim"].model_copy(
                        update={"preconditions": None}
                    ),
                }
            }
        )
        denied = ConfirmedWriteTools(
            FakeBankWrites(
                session.config["configurable"]["session"], fakebank_dir, session.overlay
            ),
            session.store,
            cast(FakeStepUpGate, session.gate),
            step_up_rule(bare),
            tool_allowed(bare),
            session.audit,
            has_preconditions=has_preconditions(bare),
        )
        step = PlanStep(
            tool="disputes.create_claim",
            args={"tx_ids": [_TXN03], "answers": [], "priority_flags": []},
        )
        with pytest.raises(PolicyDenied):
            await denied.issue_plan([step], None)

    _in_one_loop(run)


@pytest.mark.usefixtures("agent_on")
@pytest.mark.parametrize("language", ["es", "pt"])
def test_single_charge_claim(
    monkeypatch: pytest.MonkeyPatch, fakebank_dir: Path, language: Language
) -> None:
    async def run() -> None:
        answers = {"card_in_possession": "yes", "contacted_merchant": "yes"}
        # In the customer's language, or the grounding check swaps it for code's fallback.
        done_text = {
            "es": "Listo, tu caso es {c1_case_id}.",
            "pt": "Pronto, seu caso é {c1_case_id}.",
        }[language]
        scripts = [
            AgentScript(
                rounds=_OPEN_ROUNDS, finals=[_turn(language, "Elige el cargo.", asked="criterion")]
            ),
            AgentScript(
                rounds=[],
                finals=[_turn(language, "¿Tienes la tarjeta contigo?", asked="dispute_question")],
            ),
            AgentScript(
                rounds=[],
                finals=[_turn(language, "¿Hablaste con el comercio?", asked="dispute_question")],
            ),
            AgentScript(
                rounds=[[("propose_plan", _claim(["t1"], answers))]],
                finals=[_turn(language, "Revisa el reclamo.")],
            ),
            AgentScript(
                rounds=[],
                finals=[_turn(language, done_text, reported_done=[0])],
            ),
        ]
        llm = ScriptedLLM({"agent": scripts})
        session = make_session(_CUSTOMER, fakebank_dir, llm, write_audit=True)
        sent_texts = _spy_unmask(monkeypatch)

        await run_recorded_turn(session, monkeypatch, _OPENING[language])
        state = await _state(session)
        assert state["pending"]["node"] == "dispute_pick"
        assert state["ui"][0].payload.multi is True
        await run_recorded_turn(session, monkeypatch, "", selection=TxSelection(tx_ids=[_TXN01]))
        await run_recorded_turn(session, monkeypatch, "sí" if language == "es" else "sim")
        await run_recorded_turn(session, monkeypatch, "sí" if language == "es" else "sim")

        state = await _state(session)
        card = state["ui"][0]
        assert card.kind == "confirm"
        assert card.payload.labels == "accept_decline"
        assert [s.tool for s in card.payload.steps] == ["disputes.create_claim"]
        assert session.store._plans and session.overlay.blocked == set()

        events = await _accept(session, monkeypatch)
        assert [t for t, _ in events].count("readback") == 1
        sent = _one(events, "reply_sent")
        case_id = next(v for v in sent["fact_values"] if re.fullmatch(r"CLM-[0-9A-F]+", v))
        assert sent["path"] == "agent"
        statuses = {s["intent"]: s["status"] for s in sent["segments"]}
        assert statuses == {"unrecognized_charge": "resolved"}
        assert session.handoff_tools.created == []
        # D14 (e): the customer got Cardy's scripted reply, not code's fallback, and the case
        # id in it came from the `case_id` fact through its placeholder.
        # (the closing line code appends follows it).
        assert sent_texts[-1].startswith(done_text.replace("{c1_case_id}", case_id) + "\n\n")
        assert case_id not in "".join(
            getattr(f, "reply", "") for script in scripts for f in script.finals
        )

    _in_one_loop(run)


async def _compromise_via_agent(
    session: Session, monkeypatch: pytest.MonkeyPatch, language: Language, picked: list[str]
) -> _Events:
    """Open the list, pick (the plan is accepted in the pick turn), Acepto. Returns the
    Acepto turn's events."""
    # `run_recorded_turn` patches the tools but builds the handoff tools from the database.
    monkeypatch.setattr(runner, "ServiceHandoffTools", lambda _ctx: session.handoff_tools)
    await run_recorded_turn(session, monkeypatch, _OPENING[language])
    await run_recorded_turn(session, monkeypatch, "", selection=TxSelection(tx_ids=picked))
    state = await _state(session)
    assert [s.tool for s in state["ui"][0].payload.steps] == [
        "cards.block_card",
        "disputes.create_claim",
    ]
    assert state["ui"][0].payload.labels == "accept_decline"
    return await _accept(session, monkeypatch)


def _compromise_script(language: Language, handles: list[str]) -> ScriptedLLM:
    return ScriptedLLM(
        {
            "agent": [
                AgentScript(
                    rounds=_OPEN_ROUNDS,
                    finals=[_turn(language, "Elige los cargos.", asked="criterion")],
                ),
                AgentScript(
                    rounds=[[("propose_plan", _claim(handles))]],
                    finals=[_turn(language, "Revisa el plan.")],
                ),
                # No output for the Acepto turn: if a model call wrote the result, the
                # ScriptedLLM would raise on the empty queue.
            ],
            "handoff_summary": [_SUMMARY],
        }
    )


@pytest.mark.usefixtures("agent_on")
@pytest.mark.parametrize(
    ("language", "picked"), [("es", [_TXN01, _TXN02]), ("pt", [_TXN03])], ids=["es-two", "pt-score"]
)
def test_compromise_block_and_claim(
    monkeypatch: pytest.MonkeyPatch, fakebank_dir: Path, language: Language, picked: list[str]
) -> None:
    async def run() -> None:
        llm = _compromise_script(language, [f"t{i}" for i in range(1, len(picked) + 1)])
        session = make_session(_CUSTOMER, fakebank_dir, llm, write_audit=True)
        sent_texts = _spy_unmask(monkeypatch)

        events = await _compromise_via_agent(session, monkeypatch, language, picked)
        assert [t for t, _ in events].count("readback") == 2
        agent_calls = [c for c in llm.calls if c.step == "agent"]
        assert len(agent_calls) == 2
        assert agent_calls[1].tool_results == ("accepted (block_added)",)
        assert session.overlay.blocked == {_CARD_ID}

        reply = sent_texts[-1]
        opened = get_template("dispute_claim_opened", language).split("{")[0]
        transfer = get_template("handoff_transfer", language).split("{")[0]
        assert 0 <= reply.index(opened) < reply.index(transfer)
        assert re.findall(r"CLM-[0-9A-F]+", reply)
        assert _one(events, "reply_sent")["route"] == "handoff"  # mode switched to human
        assert len(session.handoff_tools.created) == 1

    _in_one_loop(run)


def _cases(value: Any) -> Any:
    """The fake bank mints a random case id per run, so two runs can only agree on how many
    there are: each id becomes `CLM-*`."""
    if isinstance(value, str):
        return re.sub(r"CLM-[0-9A-F]+", "CLM-*", value)
    if isinstance(value, list):
        return [_cases(item) for item in value]
    return value


def _essence(packet: HandoffPacket) -> dict[str, Any]:
    """The fields D17 says the two paths share; ids, times, audit ids and LLM text left out."""
    assert packet.routing is not None and packet.risk is not None
    return {
        "reason": packet.reason,
        "queue": packet.queue,
        "priority": packet.priority,
        "evidence": sorted((e.ref, e.fraud_score) for e in packet.evidence),
        "verified_facts": [(f.fact, _cases(f.value)) for f in packet.verified_facts],
        "actions_taken": [(a.tool, _cases(a.case_ids)) for a in packet.actions_taken],
        "open_questions": packet.open_questions,
        "escalation_rules_hit": packet.escalation_rules_hit,
        "routing": packet.routing.model_dump(),
        "priority_flags": packet.risk.priority_flags,
        "focus_card": packet.focus_card,
    }


def _flag(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("AGENT_ENABLED", value)
    get_settings.cache_clear()


def test_handoff_packet_same_as_flow(monkeypatch: pytest.MonkeyPatch, fakebank_dir: Path) -> None:
    picked = [_TXN01, _TXN02]

    async def flow_run() -> HandoffPacket:
        nlu = [NLUResult(language="es", intents=["unrecognized_charge"], status="clear")]
        llm = ScriptedLLM({"nlu": nlu, "handoff_summary": [_SUMMARY]})
        session = make_session(_CUSTOMER, fakebank_dir, llm)
        await run_turn(session.graph, _OPENING["es"], config=session.config)
        await run_turn(
            session.graph, "", config=session.config, selection=TxSelection(tx_ids=picked)
        )
        token = (await _state(session))["confirmation_token_id"]
        decision = ConfirmationDecision(token_id=token, decision="confirm")
        await run_turn(session.graph, "", config=session.config, confirmation=decision)
        return session.handoff_tools.created[0]

    async def agent_run() -> HandoffPacket:
        llm = _compromise_script("es", ["t1", "t2"])
        session = make_session(_CUSTOMER, fakebank_dir, llm, write_audit=True)
        await _compromise_via_agent(session, monkeypatch, "es", picked)
        return session.handoff_tools.created[0]

    async def run() -> None:
        try:
            _flag(monkeypatch, "false")
            from_flow = await flow_run()
            _flag(monkeypatch, "true")
            from_agent = await agent_run()
        finally:
            get_settings.cache_clear()
        assert _essence(from_agent) == _essence(from_flow)

    _in_one_loop(run)


@pytest.mark.usefixtures("agent_on")
def test_r2_refused_block_reissues_claim_only(
    monkeypatch: pytest.MonkeyPatch, fakebank_dir: Path
) -> None:
    async def run() -> None:
        llm = _compromise_script("es", ["t1", "t2"])
        session = make_session(_CUSTOMER, fakebank_dir, llm, write_audit=True)
        monkeypatch.setattr(runner, "ServiceHandoffTools", lambda _ctx: session.handoff_tools)
        await run_recorded_turn(session, monkeypatch, _OPENING["es"])
        await run_recorded_turn(
            session, monkeypatch, "", selection=TxSelection(tx_ids=[_TXN01, _TXN02])
        )
        first = (await _state(session))["confirmation_token_id"]
        agent_calls = [c.step for c in llm.calls].count("agent")
        sent_texts = _spy_unmask(monkeypatch)

        async def decline() -> _Events:
            token = (await _state(session))["confirmation_token_id"]
            decision = ConfirmationDecision(token_id=token, decision="cancel")
            return await run_recorded_turn(session, monkeypatch, "", confirmation=decision)

        await decline()
        state = await _state(session)
        second = state["confirmation_token_id"]
        # The first token is cancelled and unusable; nothing was written; no model call ran.
        assert second is not None and second != first
        assert first not in session.store._plans and second in session.store._plans
        assert session.overlay.blocked == set()
        assert [c.step for c in llm.calls].count("agent") == agent_calls
        offer = get_template("dispute_block_refused_offer_claim", "es")
        assert sent_texts[-1] == offer.replace("{tx_count}", "2")
        card = state["ui"][0]
        assert card.payload.token_id == second
        assert [s.tool for s in card.payload.steps] == ["disputes.create_claim"]

        await decline()
        assert session.store._plans == {}
        assert session.overlay.blocked == set()
        assert len(session.handoff_tools.created) == 1
        packet = session.handoff_tools.created[0]
        assert packet.queue == "fraudes"
        assert packet.reason == "suspected_fraud"
        assert packet.actions_taken == []
        # The packet builder adds its own question; both refusals must be there.
        assert get_template("dispute_open_question_card_active", "es") in packet.open_questions
        assert get_template("dispute_open_question_claim_refused", "es") in packet.open_questions

    _in_one_loop(run)


@pytest.mark.usefixtures("agent_on")
def test_r2_new_list_cancels_open_claim_token(
    monkeypatch: pytest.MonkeyPatch, fakebank_dir: Path
) -> None:
    async def run() -> None:
        base = _compromise_script("es", ["t1", "t2"])
        again = AgentScript(
            rounds=_OPEN_ROUNDS, finals=[_turn("es", "Elige los cargos.", asked="criterion")]
        )
        llm = ScriptedLLM({"agent": [*base.outputs["agent"], again], "handoff_summary": [_SUMMARY]})
        session = make_session(_CUSTOMER, fakebank_dir, llm, write_audit=True)
        monkeypatch.setattr(runner, "ServiceHandoffTools", lambda _ctx: session.handoff_tools)
        await run_recorded_turn(session, monkeypatch, _OPENING["es"])
        await run_recorded_turn(
            session, monkeypatch, "", selection=TxSelection(tx_ids=[_TXN01, _TXN02])
        )
        old = (await _state(session))["confirmation_token_id"]
        assert old in session.store._plans

        # A typed turn: Cardy reads the candidates again, which replaces the confirm pause.
        await run_recorded_turn(session, monkeypatch, "mejor muéstrame los cargos otra vez")
        state = await _state(session)
        assert session.store._plans == {}
        assert state["confirmation_token_id"] is None
        assert state["pending"]["node"] == "dispute_pick"
        assert state["ui"][0].payload.multi is True

        # The old card's button now executes nothing.
        decision = ConfirmationDecision(token_id=old, decision="confirm")
        await run_recorded_turn(session, monkeypatch, "", confirmation=decision)
        assert session.overlay.blocked == set()
        assert not (await _state(session)).get("actions")
        assert not any(t == "tool_result" for t, _ in session.audit.events)
        assert session.handoff_tools.created == []

    _in_one_loop(run)
