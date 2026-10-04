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
from pydantic import BaseModel, Field, model_validator

from app.core.errors import PolicyDenied, StepUpRequired
from app.domains.conversation.agent.dispute import (
    build_claim_plan,
    check_claim,
    claim_segments,
    has_claim,
)
from app.domains.conversation.agent.refs import TurnRefs
from app.domains.conversation.flows.actions import handoff
from app.domains.conversation.flows.replacement import _card_eligible
from app.domains.conversation.graph import GraphState
from app.domains.conversation.state import AgentPlanStep, Fact, IntentSegment, SegmentStatus
from app.domains.conversation.templates import Language, TemplateKind, get_template
from app.domains.conversation.tools import BankReadTools
from app.domains.conversation.tools.executor import ConfirmedWriteTools
from app.domains.conversation.ui import (
    ConfirmEvent,
    ConfirmPayload,
    ConfirmStepView,
    OtpRequiredEvent,
    OtpRequiredPayload,
)
from app.domains.localization import mask_card
from app.domains.localization.format import CardKind
from app.domains.policy.confirmation import PlanStep, ToolArg
from app.domains.policy.escalation import rule_queue
from app.domains.policy.registry import get_policies
from app.domains.policy.tools_policy import ToolsPolicy, step_up_rule

__all__ = [
    "AGENT_ADDRESS_PAUSE",
    "AGENT_OTP_PAUSE",
    "PlanBox",
    "PlanHandoff",
    "ProposeArgs",
    "ProposedStep",
    "address_pause_update",
    "cancel_open_plan",
    "check_steps",
    "issue_stored_plan",
    "otp_pause_update",
    "otp_text",
    "plan_labels",
    "plan_segments",
    "propose_plan",
]

_TOOL_BY_ACTION = {
    "lock": "cards.lock_card",
    "block": "cards.block_card",
    "unlock": "cards.unlock_card",
    "replace": "cards.order_replacement",
    "claim": "disputes.create_claim",
}
_SUMMARY_BY_ACTION = {
    "lock": "lock_card",
    "block": "block_card",
    "unlock": "unlock_card",
    "replace": "order_replacement",
    "claim": "create_claim",
}
# (intent, route) per action: lock and block are one request type.
_INTENT_BY_ACTION = {
    "lock": ("card_block", "card_block"),
    "block": ("card_block", "card_block"),
    "unlock": ("card_unlock", "card_unlock"),
    "replace": ("replacement_request", "replacement"),
    "claim": ("unrecognized_charge", "unrecognized_charge"),
}

AGENT_OTP_PAUSE = {"flow": "agent", "node": "otp", "awaiting_slot": "otp"}
AGENT_ADDRESS_PAUSE = {"flow": "agent", "node": "address", "awaiting_slot": "address"}


class PlanHandoff(Exception):
    """A check that ends the turn in a handoff, not a rejection; `update` is the graph update."""

    def __init__(self, update: dict[str, Any]) -> None:
        super().__init__("plan_handoff")
        self.update = update


class ProposedStep(BaseModel):
    action: Literal["lock", "block", "unlock", "replace", "claim"]
    card: str | None = Field(
        default=None,
        description="Card reference from this turn's results (c1). Not for a claim step.",
    )
    address: Literal["on_file", "new"] | None = Field(
        default=None,
        description="Only for replace: send to the address on file, or to a new one.",
    )
    charges: list[str] | None = Field(
        default=None,
        description="Only for claim: the references (t1) of the charges the customer picked.",
    )
    answers: dict[str, Literal["yes", "no"]] | None = Field(
        default=None,
        description="Only for claim: the customer's yes/no answer to each dispute question id.",
    )

    @model_validator(mode="after")
    def _fields_by_action(self) -> "ProposedStep":
        if self.action == "claim":
            if self.card is not None or self.address is not None:
                raise ValueError("a claim step takes charges, not card or address")
            if not self.charges:
                raise ValueError("a claim step needs at least one charge")
            return self
        if self.card is None:
            raise ValueError("this step needs a card reference")
        if self.charges is not None or self.answers is not None:
            raise ValueError("charges and answers are only for a claim step")
        if self.action == "replace" and self.address is None:
            raise ValueError("a replace step needs address: on_file or new")
        if self.action != "replace" and self.address is not None:
            raise ValueError("address is only for a replace step")
        return self


class ProposeArgs(BaseModel):
    steps: list[ProposedStep] = Field(min_length=1)


@dataclass
class PlanBox:
    """The plan or pause accepted this turn, held until the node merges it into the update."""

    token_id: str | None = None
    event: ConfirmEvent | None = None
    after_reply: list[str] = field(default_factory=list)
    permanent_blocked: list[tuple[str, CardKind, str]] = field(default_factory=list)
    _update: dict[str, Any] = field(default_factory=dict)
    _paused: bool = False

    @property
    def opened(self) -> bool:
        return self.token_id is not None or self._paused

    def update(self) -> dict[str, Any]:
        return dict(self._update)

    def set(
        self,
        token_id: str,
        event: ConfirmEvent,
        steps: list[AgentPlanStep],
        extra: dict[str, Any] | None = None,
    ) -> None:
        self.token_id = token_id
        self.event = event
        self._paused = False
        self._update = {
            "confirmation_token_id": token_id,
            "agent_plan_steps": steps,
            "pending": {"flow": "agent", "node": "confirm", "awaiting_slot": "confirmation"},
            "ui": [event],
            "asked_ui": [event],
            **(extra or {}),
        }

    def pause(self, update: dict[str, Any]) -> None:
        """Store an OTP or address pause: steps kept, no token."""
        self.token_id = None
        self.event = None
        self._paused = True
        self._update = dict(update)

    def clear(self) -> None:
        self.token_id = None
        self.event = None
        self.after_reply = []
        self.permanent_blocked = []
        self._update = {}
        self._paused = False


def plan_segments(
    steps: list[AgentPlanStep], status: SegmentStatus, awaiting_slot: str | None = None
) -> list[IntentSegment]:
    """One segment per distinct intent, in step order. A plan with a claim step is one
    `unrecognized_charge` segment, its block step included (D18)."""
    if has_claim(steps):
        claimed = claim_segments(status)[0]
        if awaiting_slot is not None:
            claimed["awaiting_slot"] = awaiting_slot
        return [claimed]
    segments: list[IntentSegment] = []
    seen: set[str] = set()
    for step in steps:
        intent, route = _INTENT_BY_ACTION[step["action"]]
        if intent in seen:
            continue
        seen.add(intent)
        segment: IntentSegment = {"intent": intent, "route": route, "status": status}
        if awaiting_slot is not None:
            segment["awaiting_slot"] = awaiting_slot
        segments.append(segment)
    return segments


def plan_labels(steps: list[AgentPlanStep], language: Language) -> dict[str, Any]:
    """The `agent_labels` of a turn that ended on a plan or a plan pause."""
    pairs = (
        [_INTENT_BY_ACTION["claim"]]
        if has_claim(steps)
        else [_INTENT_BY_ACTION[step["action"]] for step in steps]
    )
    return {
        "language": language,
        "status": "clear",
        "intents": list(dict.fromkeys(intent for intent, _ in pairs)),
        "route": pairs[0][1],
    }


def otp_text(language: Language) -> str:
    """The code text for the OTP pause when Cardy's own reply is not used (D8)."""
    return get_template("otp_required", language)


def _step_up_tool(steps: list[AgentPlanStep]) -> str:
    rule = step_up_rule(get_policies().tools)
    for step in steps:
        tool = _TOOL_BY_ACTION[step["action"]]
        if rule(tool, {"address_ref": step.get("address_ref")}):
            return tool
    return _TOOL_BY_ACTION[steps[0]["action"]]


def otp_pause_update(steps: list[AgentPlanStep], language: Language) -> dict[str, Any]:
    event = OtpRequiredEvent(
        kind="otp_required",
        payload=OtpRequiredPayload(tool=_step_up_tool(steps), cancellable=True),
    )
    return {
        "agent_plan_steps": steps,
        "pending": dict(AGENT_OTP_PAUSE),
        "ui": [event],
        "asked_ui": [event],
        "intent_segments": plan_segments(steps, "awaiting", "otp"),
    }


def address_pause_update(
    steps: list[AgentPlanStep], language: Language
) -> tuple[dict[str, Any], str]:
    """The address pause update and the question text (`address_ask` or `_multi`)."""
    count = sum(1 for step in steps if step["action"] == "replace")
    kind: TemplateKind = "address_ask" if count == 1 else "address_ask_multi"
    update = {
        "agent_plan_steps": steps,
        "pending": dict(AGENT_ADDRESS_PAUSE),
        "intent_segments": plan_segments(steps, "awaiting", "address"),
    }
    return update, get_template(kind, language)


async def check_steps(
    steps: list[ProposedStep],
    refs: TurnRefs,
    bank_tools: BankReadTools,
    tools_policy: ToolsPolicy,
    state: GraphState,
    config: RunnableConfig,
) -> list[str | None]:
    """One reason code or `None` per step. A handle that is not a card of this turn is
    `unknown_reference` and is never looked up (R1); the rest read fresh details and apply
    the tool's `preconditions` from the policy. A customer who is not active, or a bank-side
    block, ends the turn in a handoff (`PlanHandoff`)."""
    write_tools: ConfirmedWriteTools = config["configurable"]["bank_write_tools"]
    language: Language = state["language"]
    escalation = get_policies().escalation
    not_active = escalation.customer_not_active
    profile = await bank_tools.get_profile()
    if profile.customer_status in not_active.statuses and any(
        _TOOL_BY_ACTION[step.action].split(".")[-1] not in not_active.allowed for step in steps
    ):
        raise PlanHandoff(
            handoff(rule_queue(escalation, "customer_not_active"), "customer_not_active", language)
        )

    claim = next((step for step in steps if step.action == "claim"), None)
    if claim is not None:
        return check_claim(
            [step.action for step in steps], claim.charges, claim.answers, refs, state
        )

    blocked_ids = {refs.card_id(step.card or "") for step in steps if step.action == "block"} - {
        None
    }
    replace_addresses = {step.address for step in steps if step.action == "replace"}
    codes: list[str | None] = []
    for step in steps:
        card_id = refs.card_id(step.card or "")
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
            elif pre.block_origin_in is not None:
                origin = await write_tools.get_block_origin(card_id, "card_unlock")
                if origin.kind == "bank_side":
                    side = escalation.bank_side_queues
                    queue = {
                        "past_due": side.past_due,
                        "fraud": side.fraud,
                        "bank_status": side.bank_status,
                    }.get(origin.reason or "", side.customer_status)
                    raise PlanHandoff(handoff(queue, "bank_side_block", language))
                if origin.kind == "customer_block":
                    code = "permanent_block"
                elif origin.kind not in pre.block_origin_in:
                    code = "not_locked"
            elif pre.replacement_eligible:
                eligible, _ = await _card_eligible(state, config, card_id)
                if not eligible or card_id in blocked_ids:
                    code = "not_eligible"
                elif len(replace_addresses) > 1:
                    code = "address_mismatch"
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


async def issue_stored_plan(
    state: GraphState, config: RunnableConfig, steps: list[AgentPlanStep]
) -> tuple[str, ConfirmEvent]:
    """Issue the confirmation plan for stored steps. `StepUpRequired` and `PolicyDenied`
    propagate; the caller decides what to say."""
    bank_tools: BankReadTools = config["configurable"]["bank_tools"]
    write_tools: ConfirmedWriteTools = config["configurable"]["bank_write_tools"]
    plan_steps: list[PlanStep] = []
    views: list[ConfirmStepView] = []
    address_masked: str | None = None
    for step in steps:
        details = await bank_tools.get_card_details(step["card_id"])
        tool = _TOOL_BY_ACTION[step["action"]]
        call_args: dict[str, ToolArg] = {"card_id": step["card_id"]}
        facts = [Fact(key="card_mask", value=mask_card(details.last4), source=details.source)]
        if step["action"] == "block":
            # The block reason is set here, never by the model (S1 D8).
            call_args["reason"] = "lost_or_stolen"
        elif step["action"] == "replace":
            address_ref = step.get("address_ref")
            call_args["address_ref"] = address_ref
            if address_ref == "on_file":
                if address_masked is None:
                    city = (await bank_tools.get_profile()).city
                    address_masked = f"•••, {city}" if city else "•••"
                facts.append(
                    Fact(key="address_masked", value=address_masked, source=details.source)
                )
        plan_steps.append(PlanStep(tool=tool, args=call_args))
        views.append(
            ConfirmStepView(tool=tool, summary_key=_SUMMARY_BY_ACTION[step["action"]], facts=facts)
        )
    plan = await write_tools.issue_plan(plan_steps, None)
    event = ConfirmEvent(
        kind="confirm",
        payload=ConfirmPayload(token_id=plan.token_id, steps=views, labels="accept_decline"),
    )
    return plan.token_id, event


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
    language: Language = state["language"]
    codes = await check_steps(args.steps, refs, bank_tools, get_policies().tools, state, config)
    if any(code is not None for code in codes):
        for step, code in zip(args.steps, codes, strict=True):
            card_id = refs.card_id(step.card or "")
            if code == "permanent_block" and card_id is not None:
                if all(card_id != known[0] for known in box.permanent_blocked):
                    details = await bank_tools.get_card_details(card_id)
                    box.permanent_blocked.append((card_id, details.kind, details.last4))
        return _rejected(args.steps, codes)

    await cancel_open_plan(state, config, box)

    claim = next((step for step in args.steps if step.action == "claim"), None)
    if claim is not None:
        # Code builds the whole claim plan (D10); it never reads the model's steps again.
        return await build_claim_plan(state, config, refs, box, claim.answers)

    kept_steps: list[AgentPlanStep] = []
    for step in args.steps:
        card_id = refs.card_id(step.card or "")
        assert card_id is not None  # check_steps accepted it
        kept: AgentPlanStep = {"action": step.action, "card_id": card_id}
        if step.action == "replace" and step.address == "on_file":
            kept["address_ref"] = "on_file"
        kept_steps.append(kept)

    needs_address = any(
        step["action"] == "replace" and "address_ref" not in step for step in kept_steps
    )
    if needs_address and await write_tools.is_step_up_valid():
        update, question = address_pause_update(kept_steps, language)
        box.pause(update)
        box.after_reply.append(question)
        return "accepted (address_required)"
    try:
        token_id, event = await issue_stored_plan(state, config, kept_steps)
    except StepUpRequired:
        box.pause(otp_pause_update(kept_steps, language))
        return "accepted (step_up_required)"
    except PolicyDenied:
        return _rejected(args.steps, ["tool_not_allowed"] * len(args.steps))
    box.set(token_id, event, kept_steps)
    return "accepted"


def _rejected(steps: list[ProposedStep], codes: list[str | None]) -> str:
    detail = ", ".join(
        f"{step.card or 'claim'}: {code or 'ok'}" for step, code in zip(steps, codes, strict=True)
    )
    return f"rejected ({detail})"
