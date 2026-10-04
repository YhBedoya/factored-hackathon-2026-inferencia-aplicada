"""The code nodes for the agent's OTP and address pauses (S2 D10, D11, D13, D15, D18).

`agent_step_up` is the turn at the agent OTP pause: a verified step-up continues to the
address question or to the plan card, Cancel drops the stored steps, anything else sends
the OTP UI again. `agent_address` is the typed address at the address pause: it goes to
the vault and never to the LLM (R5). Both are code-only until the plan card is out; with
the LLM up the plan-ready and cancelled texts go to the agent node as `agent_code_text`,
with the LLM down they are the reply itself (D18).

This module never imports the LLM package (R6). It reads write tools and the vault only
through `config["configurable"]`, like `confirm.py`.
"""

from typing import Any

from langchain_core.runnables import RunnableConfig

from app.core.errors import StepUpRequired
from app.domains.conversation.agent.plan import (
    address_pause_update,
    issue_stored_plan,
    otp_pause_update,
    otp_text,
    plan_labels,
    plan_segments,
)
from app.domains.conversation.graph import GraphState
from app.domains.conversation.state import AgentPlanStep
from app.domains.conversation.templates import Language, get_template
from app.domains.conversation.tools.executor import ConfirmedWriteTools
from app.domains.safety.vault import AddressVault

__all__ = ["agent_address", "agent_step_up"]

_CLEARED: dict[str, Any] = {
    "pending": None,
    "confirmation_token_id": None,
    "agent_plan_steps": None,
}


def _with_text(
    state: GraphState,
    update: dict[str, Any],
    text: str,
    steps: list[AgentPlanStep],
    language: Language,
    *,
    as_reply: bool = False,
) -> dict[str, Any]:
    """Attach a code text. It is Cardy's input (`agent_code_text`) unless the LLM is down
    (D18) or this turn's own reply is the text (`as_reply`): then it is `segments`, and the
    labels the agent node would have written come from here."""
    out = dict(update)
    llm_down = state.get("escalation_reason") == "llm_unavailable"
    if llm_down or as_reply:
        out["segments"] = [text]
        if steps:
            out["agent_labels"] = plan_labels(steps, language)
    else:
        out["agent_code_text"] = text
    if llm_down:
        out["escalation_reason"] = None
    return out


def _otp_again(state: GraphState, steps: list[AgentPlanStep], language: Language) -> dict[str, Any]:
    return _with_text(
        state, otp_pause_update(steps, language), otp_text(language), steps, language, as_reply=True
    )


def _plan_issued(
    state: GraphState,
    steps: list[AgentPlanStep],
    token_id: str,
    event: Any,
    language: Language,
    *,
    as_reply: bool,
) -> dict[str, Any]:
    update: dict[str, Any] = {
        "confirmation_token_id": token_id,
        "agent_plan_steps": steps,
        "pending": {"flow": "agent", "node": "confirm", "awaiting_slot": "confirmation"},
        "ui": [event],
        "asked_ui": [event],
        "intent_segments": plan_segments(steps, "awaiting", "confirmation"),
    }
    text = get_template("agent_plan_ready", language)
    return _with_text(state, update, text, steps, language, as_reply=as_reply)


async def agent_step_up(state: GraphState, config: RunnableConfig) -> dict[str, Any]:
    """The turn at the agent OTP pause (D10, D13, D15)."""
    language: Language = state.get("language", "es")
    steps = list(state.get("agent_plan_steps") or [])
    resume: str | None = state.get("resume")

    if resume == "step_up_cancel":
        # No token exists at this pause, so there is nothing to cancel: only the steps go.
        update = {
            **_CLEARED,
            "agent_plan_result": {"outcome": "declined", "steps": []},
            "intent_segments": plan_segments(steps, "cancelled"),
        }
        return _with_text(
            state, update, get_template("action_cancelled", language), steps, language
        )

    if resume != "step_up" or not steps:
        # Text, a button or a pick (D15): nothing changes, the OTP UI goes out again.
        return _otp_again(state, steps, language)

    write_tools: ConfirmedWriteTools = config["configurable"]["bank_write_tools"]
    if not await write_tools.is_step_up_valid():
        return _otp_again(state, steps, language)

    if any(step["action"] == "replace" and "address_ref" not in step for step in steps):
        update, question = address_pause_update(steps, language)
        return _with_text(state, update, question, steps, language, as_reply=True)

    try:
        token_id, event = await issue_stored_plan(state, config, steps)
    except StepUpRequired:
        return _otp_again(state, steps, language)
    update = _plan_issued(state, steps, token_id, event, language, as_reply=False)
    update["agent_plan_result"] = {
        "outcome": "issued",
        "steps": [{"action": s["action"], "card_id": s["card_id"]} for s in steps],
    }
    return update


async def agent_address(state: GraphState, config: RunnableConfig) -> dict[str, Any]:
    """The typed address at the agent address pause (D11): vaulted, never sent to the LLM."""
    language: Language = state.get("language", "es")
    vault: AddressVault = config["configurable"]["vault"]
    ref = vault.put_address(state["user_text"])
    if not state.get("agent_enabled"):
        # Kill switch flipped while the address question was open: the address is vaulted
        # and dropped, the stored plan goes, and the customer gets the code reply.
        steps_dropped = list(state.get("agent_plan_steps") or [])
        update = {
            **_CLEARED,
            "agent_plan_result": {"outcome": "declined", "steps": []},
            "intent_segments": plan_segments(steps_dropped, "cancelled"),
        }
        return _with_text(
            state,
            update,
            get_template("action_cancelled", language),
            steps_dropped,
            language,
            as_reply=True,
        )
    steps: list[AgentPlanStep] = []
    for step in state.get("agent_plan_steps") or []:
        kept = AgentPlanStep(**step)
        if kept["action"] == "replace" and "address_ref" not in kept:
            kept["address_ref"] = ref
        steps.append(kept)

    try:
        token_id, event = await issue_stored_plan(state, config, steps)
    except StepUpRequired:
        return _otp_again(state, steps, language)
    return _plan_issued(state, steps, token_id, event, language, as_reply=True)
