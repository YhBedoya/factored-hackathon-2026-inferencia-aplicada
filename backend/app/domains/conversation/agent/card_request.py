"""Card-request checks for the agent path (D9-C, spec AS7, D9). Eligibility is decided here
from `get_policies()` and the read tools, never by the model (R8). This module does not
import the LLM package (R6)."""

from typing import Any, Literal, cast
from uuid import UUID

from langchain_core.runnables import RunnableConfig

from app.core.actions import ActionResult
from app.core.errors import StepUpRequired
from app.domains.conversation.graph import GraphState
from app.domains.conversation.state import AgentPlanStep
from app.domains.conversation.templates import Language, get_template
from app.domains.conversation.tools import BankReadTools
from app.domains.conversation.tools.executor import ConfirmedWriteTools
from app.domains.handoff.schemas import CardRequestBlock
from app.domains.localization import mask_card
from app.domains.policy.registry import get_policies
from app.domains.policy.tools_policy import Preconditions

__all__ = ["agent_profile_form", "card_request_block", "check_close", "check_open"]


async def check_open(
    kind: Literal["credit", "debit"],
    bank_tools: BankReadTools,
    write_tools: ConfirmedWriteTools,
) -> str | None:
    """The first failing `request_eligible` check for opening a card, or `None`.

    Order is fixed by the contract: `customer_not_active`, `card_past_due`,
    `card_cap_reached`, `request_pending`. The customer comes from the session through
    the tools (R1); nothing here takes an id.
    """
    policies = get_policies()
    profile = await bank_tools.get_profile()
    if profile.customer_status in policies.escalation.customer_not_active.statuses:
        return "customer_not_active"

    cards = [card for card in await bank_tools.list_cards() if card.status != "Closed"]
    for card in cards:
        details = await bank_tools.get_card_details(card.card_id)
        if details.days_past_due is not None and details.days_past_due > 0:
            return "card_past_due"

    cap = policies.card_requests.max_cards_per_kind[kind]
    if sum(1 for card in cards if card.kind == kind) >= cap:
        return "card_cap_reached"

    if (await write_tools.pending_card_requests()).open_pending:
        return "request_pending"
    return None


async def check_close(
    card_id: str,
    reason: str | None,
    bank_tools: BankReadTools,
    write_tools: ConfirmedWriteTools,
    pre: Preconditions | None,
) -> str | None:
    """The first failing `cards.request_closure` precondition, or `None`.

    Order is fixed by the contract: `already_in_state`, `closure_pending`,
    `invalid_reason`. The card id was resolved from this turn's references (R1); the
    reason is checked against `card_requests.yaml` `cancel_reasons` (R8). A non-zero
    balance is not checked here: the staff decides at decision time.
    """
    if pre is None:
        return None
    details = await bank_tools.get_card_details(card_id)
    if details.status in pre.status_not_in:
        return "already_in_state"
    if (
        pre.closure_pending is False
        and card_id in (await write_tools.pending_card_requests()).close_card_ids
    ):
        return "closure_pending"
    if pre.reason_in_policy and reason not in get_policies().card_requests.cancel_reasons:
        return "invalid_reason"
    return None


async def card_request_block(
    result: ActionResult, bank_tools: BankReadTools | None
) -> CardRequestBlock:
    """The packet's `card_request` from a verified `request_card` or `request_closure`
    result (I9 read-back).

    Only the request id, the reference, the card kind and, for a close, the mask and the
    reason code come from the read-back: no form value and no field content reaches the
    packet (R5). An opening has no card yet, so its mask stays null.
    """
    assert result.verified and result.tracking_id is not None
    readback = result.readback
    if result.tool == "cards.request_closure":
        return CardRequestBlock(
            request_id=UUID(str(readback["request_id"])),
            reference=result.tracking_id,
            kind="close",
            card_kind=cast(Literal["credit", "debit"], readback["card_kind"]),
            card_mask=mask_card(str(readback["last4"])),
            reason_code=str(readback["reason"]),
        )
    return CardRequestBlock(
        request_id=UUID(str(readback["request_id"])),
        reference=result.tracking_id,
        kind="open",
        card_kind=cast(Literal["credit", "debit"], readback["kind"]),
        card_mask=None,
        reason_code=None,
    )


_CLEARED: dict[str, Any] = {
    "pending": None,
    "confirmation_token_id": None,
    "agent_plan_steps": None,
    "card_request_kind": None,
    "profile_changed_fields": None,
}


async def agent_profile_form(state: GraphState, config: RunnableConfig) -> dict[str, Any]:
    """The turn at the agent profile-form pause (D9-C D11). Code only, no LLM call.

    The form values were staged in the vault by the POST route; this node sees only the
    changed field *names* (`form_changed_fields`) and never reads a value (R5). Send goes
    on to the OTP (or straight to the plan card when step-up is already valid); Cancel and
    the kill switch end the request; anything else shows the form again.
    """
    # Imported here: `plan` and `step_up` import this module for `check_open`.
    from app.domains.conversation.agent.plan import (
        AGENT_PROFILE_FORM_PAUSE,
        issue_stored_plan,
        otp_pause_update,
        otp_text,
        plan_segments,
    )
    from app.domains.conversation.agent.step_up import _plan_issued, _with_text
    from app.domains.conversation.ui import ProfileFormEvent, ProfileFormPayload

    language: Language = state.get("language", "es")
    steps: list[AgentPlanStep] = list(state.get("agent_plan_steps") or [])
    resume = state.get("resume")

    if resume == "profile_form_cancel" or not state.get("agent_enabled") or not steps:
        # Cancel, or the kill switch flipped while the form was open: the request ends and
        # nothing was written. No token exists at this pause.
        update = {
            **_CLEARED,
            "agent_plan_result": {"outcome": "declined", "steps": []},
            "intent_segments": plan_segments(steps, "cancelled") if steps else [],
        }
        return _with_text(
            state,
            update,
            get_template("action_cancelled", language),
            steps,
            language,
            as_reply=True,
        )

    if resume != "profile_form":
        # Typed text, a button or a pick: nothing changes, the form goes out again with
        # the text it was first asked with.
        kind = state.get("card_request_kind") or steps[0].get("kind")
        assert kind is not None
        event = ProfileFormEvent(kind="profile_form", payload=ProfileFormPayload(card_kind=kind))
        asked = state.get("open_question")
        update = {
            "agent_plan_steps": steps,
            "pending": dict(AGENT_PROFILE_FORM_PAUSE),
            "ui": [event],
            "asked_ui": [event],
            "intent_segments": plan_segments(steps, "awaiting", "profile_form"),
        }
        if asked is not None:
            update["segments"] = [asked["text"]]
        return update

    changed = list(state.get("form_changed_fields") or [])
    # Names only, in state before the plan is built: it labels the plan card from them.
    planned = cast(GraphState, {**state, "profile_changed_fields": changed})
    try:
        token_id, plan_event = await issue_stored_plan(planned, config, steps)
    except StepUpRequired:
        update = otp_pause_update(steps, language)
        update["profile_changed_fields"] = changed
        return _with_text(state, update, otp_text(language), steps, language, as_reply=True)
    update = _plan_issued(state, steps, token_id, plan_event, language, as_reply=True)
    update["profile_changed_fields"] = changed
    return update
