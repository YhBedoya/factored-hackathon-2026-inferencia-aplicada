"""`propose_plan` and the plan check (D8-D11): the agent's only write capability is to
*propose*. Every step names a card by this turn's reference handle; code resolves it,
re-reads the card, applies the `preconditions` of `policies/tools.yaml` (R8) and only then
issues a confirmation plan. The token stays in server state and in the code-rendered card;
the string handed back to the model never carries it (R6). This module does not import
the LLM package (R6).
"""

from dataclasses import dataclass, field
from typing import Any, Literal

from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field

from app.core.errors import PolicyDenied
from app.domains.conversation.agent.refs import TurnRefs
from app.domains.conversation.graph import GraphState
from app.domains.conversation.state import AgentPlanStep, Fact
from app.domains.conversation.tools import BankReadTools
from app.domains.conversation.tools.executor import ConfirmedWriteTools
from app.domains.conversation.ui import ConfirmEvent, ConfirmPayload, ConfirmStepView
from app.domains.localization import mask_card
from app.domains.policy.confirmation import PlanStep
from app.domains.policy.registry import get_policies
from app.domains.policy.tools_policy import ToolsPolicy

__all__ = [
    "PlanBox",
    "ProposeArgs",
    "ProposedStep",
    "cancel_open_plan",
    "check_steps",
    "propose_plan",
]

_TOOL_BY_ACTION = {"lock": "cards.lock_card", "block": "cards.block_card"}
_SUMMARY_BY_ACTION = {"lock": "lock_card", "block": "block_card"}


class ProposedStep(BaseModel):
    action: Literal["lock", "block"]
    card: str = Field(description="Card reference from this turn's results (c1).")


class ProposeArgs(BaseModel):
    steps: list[ProposedStep] = Field(min_length=1)


@dataclass
class PlanBox:
    """The plan accepted this turn, held until the node merges it into the graph update."""

    token_id: str | None = None
    event: ConfirmEvent | None = None
    _update: dict[str, Any] = field(default_factory=dict)

    def update(self) -> dict[str, Any]:
        return dict(self._update)

    def set(self, token_id: str, event: ConfirmEvent, steps: list[AgentPlanStep]) -> None:
        self.token_id = token_id
        self.event = event
        self._update = {
            "confirmation_token_id": token_id,
            "agent_plan_steps": steps,
            "pending": {"flow": "agent", "node": "confirm", "awaiting_slot": "confirmation"},
            "ui": [event],
            "asked_ui": [event],
        }

    def clear(self) -> None:
        self.token_id = None
        self.event = None
        self._update = {}


async def check_steps(
    steps: list[ProposedStep],
    refs: TurnRefs,
    bank_tools: BankReadTools,
    tools_policy: ToolsPolicy,
) -> list[str | None]:
    """One reason code or `None` per step. A handle that is not a card of this turn is
    `unknown_reference` and is never looked up (R1); the rest read fresh details and apply
    the tool's `preconditions` from the policy."""
    codes: list[str | None] = []
    for step in steps:
        card_id = refs.card_id(step.card)
        if card_id is None:
            codes.append("unknown_reference")
            continue
        policy = tools_policy.tools.get(_TOOL_BY_ACTION[step.action])
        pre = policy.preconditions if policy is not None else None
        details = await bank_tools.get_card_details(card_id)
        code: str | None = None
        if pre is not None:
            if details.status in pre.status_not_in:
                code = "already_in_state"
            elif pre.locked is False and details.locked:
                code = "already_locked"
        codes.append(code)
    return codes


async def cancel_open_plan(
    state: GraphState, config: RunnableConfig, box: PlanBox
) -> dict[str, Any]:
    """Cancel whatever plan is open (in state or in the box) and return the clearing update."""
    write_tools: ConfirmedWriteTools = config["configurable"]["bank_write_tools"]
    for token_id in {state.get("confirmation_token_id"), box.token_id} - {None}:
        assert token_id is not None
        await write_tools.cancel_plan(token_id)
    box.clear()
    return {"confirmation_token_id": None, "agent_plan_steps": None, "pending": None}


async def propose_plan(
    args: ProposeArgs,
    *,
    state: GraphState,
    config: RunnableConfig,
    refs: TurnRefs,
    box: PlanBox,
) -> str:
    bank_tools: BankReadTools = config["configurable"]["bank_tools"]
    write_tools: ConfirmedWriteTools = config["configurable"]["bank_write_tools"]
    codes = await check_steps(args.steps, refs, bank_tools, get_policies().tools)
    if any(code is not None for code in codes):
        return _rejected(codes)

    await cancel_open_plan(state, config, box)

    plan_steps: list[PlanStep] = []
    kept_steps: list[AgentPlanStep] = []
    views: list[ConfirmStepView] = []
    for step in args.steps:
        card_id = refs.card_id(step.card)
        assert card_id is not None  # check_steps accepted it
        details = await bank_tools.get_card_details(card_id)
        tool = _TOOL_BY_ACTION[step.action]
        # The block reason is set here, never by the model (D8).
        call_args: dict[str, Any] = {"card_id": card_id}
        if step.action == "block":
            call_args["reason"] = "lost_or_stolen"
        plan_steps.append(PlanStep(tool=tool, args=call_args))
        kept_steps.append({"action": step.action, "card_id": card_id})
        views.append(
            ConfirmStepView(
                tool=tool,
                summary_key=_SUMMARY_BY_ACTION[step.action],
                facts=[
                    Fact(key="card_mask", value=mask_card(details.last4), source=details.source)
                ],
            )
        )
    try:
        plan = await write_tools.issue_plan(plan_steps, None)
    except PolicyDenied:
        return _rejected(["tool_not_allowed"] * len(args.steps))
    box.set(
        plan.token_id,
        ConfirmEvent(
            kind="confirm",
            payload=ConfirmPayload(token_id=plan.token_id, steps=views, labels="accept_decline"),
        ),
        kept_steps,
    )
    return "accepted"


def _rejected(codes: list[str | None]) -> str:
    detail = "; ".join(f"step {i}: {code or 'ok'}" for i, code in enumerate(codes, start=1))
    return f"rejected ({detail})"
