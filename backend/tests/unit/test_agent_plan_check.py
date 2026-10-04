"""The agent's plan check (D8, D9, D10): another customer's card is refused (R1) and the
YAML preconditions reject a no-op step. Handlers are called directly; no LLM, no graph turn."""

import asyncio
from pathlib import Path
from typing import cast

import pytest

from app.core.errors import PolicyDenied
from app.domains.conversation.agent.plan import PlanBox, ProposeArgs, ProposedStep, propose_plan
from app.domains.conversation.agent.reads import read_tools
from app.domains.conversation.agent.refs import TurnRefs
from app.domains.conversation.graph import GraphState
from app.domains.policy.confirmation import PlanStep
from tests.conftest import ScriptedLLM, make_session


async def _read_cards(session, state: GraphState, refs: TurnRefs) -> None:  # type: ignore[no-untyped-def]
    tool = next(t for t in read_tools(state, session.config, refs) if t.name == "card_status")
    await tool.handler(tool.args_schema())


def test_r1_other_customers_card_refused(fakebank_dir: Path) -> None:
    async def run() -> None:
        session = make_session("CLI-TFMULTI00001", fakebank_dir, ScriptedLLM({}))
        state = cast(GraphState, {"language": "es", "country": "MX"})
        refs = TurnRefs("es", "MX")
        await _read_cards(session, state, refs)

        box = PlanBox()
        steps = [
            ProposedStep(action="lock", card="PRD-TFS2CRED0001"),
            ProposedStep(action="block", card="c99"),
        ]
        result = await propose_plan(
            ProposeArgs(steps=steps), state=state, config=session.config, refs=refs, box=box
        )
        assert result.startswith("rejected")
        assert result.count("unknown_reference") == 2
        assert session.store._plans == {}
        assert session.overlay.locked == set()
        assert session.overlay.blocked == set()
        assert box.update() == {}

    asyncio.run(run())


def test_precondition_rejects_blocked_card(fakebank_dir: Path) -> None:
    async def run() -> None:
        session = make_session("CLI-TFMULTI00001", fakebank_dir, ScriptedLLM({}))
        state = cast(GraphState, {"language": "es", "country": "MX"})
        refs = TurnRefs("es", "MX")
        await _read_cards(session, state, refs)
        handle = "c1"
        card_id = refs.card_id(handle)
        assert card_id is not None
        session.overlay.blocked.add(card_id)

        box = PlanBox()
        result = await propose_plan(
            ProposeArgs(steps=[ProposedStep(action="lock", card=handle)]),
            state=state,
            config=session.config,
            refs=refs,
            box=box,
        )
        assert "already_in_state" in result
        assert session.store._plans == {}

        write_tools = session.config["configurable"]["bank_write_tools"]
        with pytest.raises(PolicyDenied):
            await write_tools.issue_plan(
                [PlanStep(tool="cards.get_block_origin", args={"card_id": card_id})],
                None,
            )

    asyncio.run(run())
