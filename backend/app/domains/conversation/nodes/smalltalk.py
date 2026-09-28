"""Fixed-template replies for conversation basics, no LLM call (B3, D16, D20).

`smalltalk` is where `_entry` and `route` both send a turn that carries only
conversation-management content (`greeting`, `thanks_close`, `affirm`,
`deny`), or a button/step-up resume that doesn't match an open pause. Two
different shapes reach it:

* Via `_entry`, before `understand` ever runs this turn (`state["nlu"]` is
  still `None`, reset by `load_session`): a `confirmation`/`resume` that
  doesn't match the open pause (a stale token, or nothing pending at all).
* Via `route`, after `understand` ran and found only management intents.
  When a pause is open but waiting on something these intents don't answer
  (D15: it isn't a fitting continuation, or `route` would have sent the
  turn straight to the flow node instead), Cardy reminds the customer what
  she's still waiting on -- the OTP prompt again, or that nothing else is
  pending -- rather than a generic greeting or "thanks" reply. `pending` is
  left untouched either way (the caller reads it straight off state), so a
  turn that lands here never discards a queued action.
"""

from typing import Any

from app.domains.conversation.graph import GraphState
from app.domains.conversation.templates import TemplateKind, get_template

__all__ = ["smalltalk"]


def smalltalk(state: GraphState) -> dict[str, Any]:
    """Fixed ES/PT template for a conversation-management turn (D16, D20)."""
    language = state.get("language", "es")
    pending = state.get("pending")
    nlu = state.get("nlu")

    if nlu is None:
        # Entry-level: a button confirmation or a step-up resume that
        # `_entry` couldn't match to an open pause. The resume case still
        # names what it's waiting on; a stale/absent confirmation doesn't.
        if state.get("resume") == "step_up":
            return {"segments": [get_template("otp_required", language)]}
        return {"segments": [get_template("nothing_pending", language)]}

    if pending is not None:
        # A pause is open, and it isn't waiting on what this turn carries
        # (route only sends a fitting continuation to the flow node itself).
        kind: TemplateKind = (
            "otp_required" if pending["awaiting_slot"] == "otp" else "nothing_pending"
        )
        return {"segments": [get_template(kind, language)]}

    if nlu.intents == ["greeting"]:
        customer_name = state.get("customer_name")
        if customer_name:
            text = get_template("greeting_named", language).replace(
                "{customer_name}", customer_name
            )
            return {"segments": [text]}
        return {"segments": [get_template("greeting", language)]}

    if "thanks_close" in nlu.intents:
        return {"segments": [get_template("thanks_close", language)]}

    # A bare affirm/deny with nothing pending to confirm.
    return {"segments": [get_template("nothing_pending", language)]}
