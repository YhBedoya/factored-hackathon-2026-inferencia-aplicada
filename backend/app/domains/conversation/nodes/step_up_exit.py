"""Code-only exits from an OTP pause (S2 D28, D30).

`step_up_failed` is the server-triggered handoff after too many wrong OTP codes: it sets
the escalation reason and leaves `pending` alone, so `handoff_summary` and `handoff` read
`pending.flow` and clear it in the same turn (the turn ends with no pause). `otp_cancel`
is the Cancel button at a pipeline OTP pause. Neither node reads `user_text`, calls the
LLM or writes anything (R6).
"""

from typing import Any

from langchain_core.runnables import RunnableConfig

from app.domains.conversation.agent.plan import plan_labels, plan_segments
from app.domains.conversation.graph import GraphState
from app.domains.conversation.templates import Language, get_template

__all__ = ["otp_cancel", "step_up_failed"]


def _flow_intent(flow: str) -> str:
    # Inside the function: graph imports the nodes, so a module-level import cycles.
    from app.domains.conversation.graph import _FLOW_INTENT

    return _FLOW_INTENT.get(flow, flow)


async def step_up_failed(state: GraphState, config: RunnableConfig) -> dict[str, Any]:
    """Too many wrong OTP codes: hand off to fraudes with the fixed text (D28)."""
    language: Language = state.get("language", "es")
    pending = state.get("pending")
    update: dict[str, Any] = {
        "escalation_reason": "step_up_failed",
        "agent_plan_steps": None,
        "confirmation_token_id": None,
        "segments": [get_template("step_up_failed_handoff", language)],
    }
    if pending is not None and pending["flow"] == "agent":
        steps = list(state.get("agent_plan_steps") or [])
        update["intent_segments"] = plan_segments(steps, "handoff")
        if steps:
            update["agent_labels"] = plan_labels(steps, language)
    elif pending is not None:
        update["intent_segments"] = [
            {"intent": _flow_intent(pending["flow"]), "route": pending["flow"], "status": "handoff"}
        ]
    return update


async def otp_cancel(state: GraphState, config: RunnableConfig) -> dict[str, Any]:
    """Cancel at a pipeline OTP pause: no token exists yet, so only the pause goes (D30)."""
    language: Language = state.get("language", "es")
    pending = state.get("pending")
    update: dict[str, Any] = {
        "pending": None,
        "confirmation_token_id": None,
        "segments": [get_template("action_cancelled", language)],
    }
    if pending is not None:
        update["intent_segments"] = [
            {
                "intent": _flow_intent(pending["flow"]),
                "route": pending["flow"],
                "status": "cancelled",
            }
        ]
    return update
