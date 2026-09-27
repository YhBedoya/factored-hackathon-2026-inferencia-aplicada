"""The turn's conditional edge after `understand`: pick a handler (D8, D14).

`route` is a pure function of state -- no config, no I/O, no LLM call -- so
`build_graph` (T11) can pass it straight to `add_conditional_edges`. Priority
is exactly the acceptance line's order: a missing NLU result always falls
back first; then the three "we don't do that at all" statuses always go to
`unsupported`, even if the intent would otherwise be `card_status`; then a
fresh `card_status` intent or a pending `card_hint` clarification goes to
`card_info`; anything else -- including a lone `greeting` -- is `unsupported`
too (D14: any intent other than `card_status`).
"""

from typing import Literal

from app.domains.conversation.graph import GraphState

__all__ = ["route"]

RouteResult = Literal["card_info", "unsupported", "fallback"]

_UNROUTABLE_STATUSES = {"out_of_market", "out_of_scope", "injection_suspected"}


def route(state: GraphState) -> RouteResult:
    """Pick the next node for this turn (D8, D12, D14)."""
    nlu = state.get("nlu")
    if nlu is None:
        return "fallback"
    if nlu.status in _UNROUTABLE_STATUSES:
        return "unsupported"

    pending = state.get("pending")
    awaits_card_hint = (
        pending is not None
        and pending["flow"] == "card_info"
        and pending["awaiting_slot"] == "card_hint"
    )
    if awaits_card_hint or "card_status" in nlu.intents:
        return "card_info"
    return "unsupported"
