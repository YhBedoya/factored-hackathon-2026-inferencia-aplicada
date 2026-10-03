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
  she's still waiting on -- the OTP prompt again, or a reminder that she
  still needs the answer to her last question -- rather than a generic
  greeting or "thanks" reply. That flow pause is left untouched, so a turn
  that lands here never discards a queued action.

Closing (`anything_else`): thanks, or a bare "no", with nothing pending gets
"anything else?" and opens a `smalltalk.anything_else` pause. A "no",
another thanks or a goodbye to it ends the conversation: `farewell`, the
turn state cleared, and a `conversation_closed` UI event so the caller
starts over. A "yes" gets `ask_what_else`; a new card request simply
replaces the pause (`route` sends it to `enqueue`, P1).
"""

from typing import Any

from app.domains.conversation.graph import GraphState
from app.domains.conversation.schemas import NLUSlots
from app.domains.conversation.state import Pending
from app.domains.conversation.templates import Language, get_template
from app.domains.conversation.ui import ConversationClosedEvent

__all__ = ["smalltalk"]

_ANYTHING_ELSE: Pending = {
    "flow": "smalltalk",
    "node": "anything_else",
    "awaiting_slot": "anything_else",
}


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

    if state.get("degraded") and nlu.status == "ambiguous" and not nlu.intents:
        # D8: the degraded classifier couldn't tell what she meant. The pause (if
        # any) stays open; the second miss in a row is `route`'s handoff.
        return {"segments": [get_template("clarify_rephrase", language)]}

    intents = nlu.intents
    closing = "deny" in intents or "thanks_close" in intents

    if pending is not None and pending["awaiting_slot"] == "anything_else":
        if closing:
            return _close(language)
        if "affirm" in intents:
            return {"pending": None, "segments": [get_template("ask_what_else", language)]}
        # A lone greeting: answer it and keep waiting.

    elif pending is not None:
        # A flow pause is open, and it isn't waiting on what this turn
        # carries (route only sends a fitting continuation to the flow node).
        if pending["awaiting_slot"] == "otp":
            return {"segments": [get_template("otp_required", language)]}
        return {"segments": [get_template("pending_reminder", language)]}

    if intents == ["greeting"]:
        customer_name = state.get("customer_name")
        if customer_name:
            text = get_template("greeting_named", language).replace(
                "{customer_name}", customer_name
            )
            return {"segments": [text]}
        return {"segments": [get_template("greeting", language)]}

    if closing:
        return {"pending": _ANYTHING_ELSE, "segments": [get_template("anything_else", language)]}

    # A bare affirm with nothing pending.
    return {"segments": [get_template("ask_what_else", language)]}


def _close(language: Language) -> dict[str, Any]:
    """Say goodbye and clear the turn state; the caller ends the conversation."""
    return {
        "pending": None,
        "intent_queue": [],
        "selected_card_id": None,
        "slots": NLUSlots(),
        "clarification_failures": 0,
        "confirmation_token_id": None,
        # The conversation is over: memory goes with it (naturalidad-cardy D3).
        "history": [],
        "summary": None,
        "segments": [get_template("farewell", language)],
        "ui": [ConversationClosedEvent(kind="conversation_closed")],
    }
