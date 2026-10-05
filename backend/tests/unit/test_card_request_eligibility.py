"""D9-C spec T7: a failed opening check is a `rejected (open: <code>)` result the agent
explains. No handoff, no form, no write (D9). Handler called directly; no LLM."""

import asyncio
from pathlib import Path
from typing import Literal, cast
from uuid import uuid4

import pytest

from app.domains.conversation.agent import card_request
from app.domains.conversation.agent.plan import PlanBox, ProposeArgs, ProposedStep, propose_plan
from app.domains.conversation.agent.refs import TurnRefs
from app.domains.conversation.graph import GraphState
from app.domains.policy.registry import get_policies
from tests.conftest import ScriptedLLM, make_session

_PENDING_OPEN = {
    "reference": "SOL-TEST",
    "kind": "open",
    "card_kind": "credit",
    "status": "pending",
    "changed_fields": [],
    "product_id": None,
    "reason_code": None,
    "created_at": "2026-10-04T00:00:00+00:00",
}


@pytest.mark.usefixtures("agent_on")
@pytest.mark.parametrize(
    ("customer", "code"),
    [
        ("CLI-TFINACT00004", "customer_not_active"),
        ("CLI-TFPASTD00005", "card_past_due"),
        ("CLI-TFMULTI00001", "card_cap_reached"),
        ("CLI-TFMULTI00001", "request_pending"),
    ],
)
def test_open_failed_check_no_handoff(
    fakebank_dir: Path, monkeypatch: pytest.MonkeyPatch, customer: str, code: str
) -> None:
    async def run() -> None:
        session = make_session(customer, fakebank_dir, ScriptedLLM({}))
        kind: Literal["credit", "debit"] = "credit"
        if code == "card_cap_reached":
            bundle = get_policies()
            caps = {**bundle.card_requests.max_cards_per_kind, "debit": 1}
            capped = bundle.model_copy(
                update={
                    "card_requests": bundle.card_requests.model_copy(
                        update={"max_cards_per_kind": caps}
                    )
                }
            )
            monkeypatch.setattr(card_request, "get_policies", lambda: capped)
            kind = "debit"
        if code == "request_pending":
            session.overlay.card_requests[uuid4()] = dict(_PENDING_OPEN)
        before = (
            dict(session.overlay.card_requests),
            dict(session.overlay.profile),
            list(session.overlay.profile_history),
        )

        state = cast(GraphState, {"language": "es", "country": "MX"})
        box = PlanBox()
        result = await propose_plan(
            ProposeArgs(steps=[ProposedStep(action="open", kind=kind)]),
            state=state,
            config=session.config,
            refs=TurnRefs("es", "MX"),
            box=box,
        )
        assert f"rejected (open: {code})" in result
        # No handoff and no form: the box stayed empty, so no `ui` or `pending` update.
        assert box.update() == {}
        assert (
            dict(session.overlay.card_requests),
            dict(session.overlay.profile),
            list(session.overlay.profile_history),
        ) == before

    asyncio.run(run())
