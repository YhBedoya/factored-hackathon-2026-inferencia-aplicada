"""The turn's conditional edge after `understand`: pick a handler (D8, D14, D20).

`route` is a pure function of state -- no config, no I/O, no LLM call -- so
`build_graph` can pass it straight to `add_conditional_edges`. Order, exactly
as `docs/plans/d2-b-card-info-block.md` §"Graph shape" pins it:

1. A missing NLU result always falls back first.
2. The three "we don't do that at all" statuses always go to `unsupported`,
   `pending` kept as-is (D14): `route` never touches it.
3. A `pending` continuation whose answer fits goes straight to that flow's
   own node (`_FLOW_NODES`) -- an unregistered flow name (no flow shipped
   for it yet) falls back to `unsupported` (P3).
4. A turn made only of conversation-management intents (`greeting`,
   `thanks_close`, `affirm`, `deny`) goes to `smalltalk`, whether or not a
   pause is still open: `smalltalk` decides which template that pause needs.
5. Anything else is a fresh (or replacing) card action, so it goes to
   `enqueue` (D20, P1).
"""

from app.domains.conversation.graph import (
    _FLOW_NODES,
    _INTENT_NODES,
    _MANAGEMENT_INTENTS,
    GraphState,
)
from app.domains.conversation.schemas import NLUResult
from app.domains.conversation.state import Pending

__all__ = ["route"]

_UNROUTABLE_STATUSES = {"out_of_market", "out_of_scope", "injection_suspected"}
_CONFIRMATION_SLOTS = {"confirmation", "address_confirm", "offer_replacement"}


def route(state: GraphState) -> str:
    """Pick the next node for this turn (D8, D12, D14, D20)."""
    nlu = state.get("nlu")
    if nlu is None:
        return "fallback"
    if nlu.status in _UNROUTABLE_STATUSES:
        return "unsupported"

    pending = state.get("pending")
    if pending is not None and _answer_fits(nlu, pending):
        return _FLOW_NODES.get(pending["flow"], "unsupported")

    if nlu.intents and all(intent in _MANAGEMENT_INTENTS for intent in nlu.intents):
        return "smalltalk"
    return "enqueue"


def _answer_fits(nlu: NLUResult, pending: Pending) -> bool:
    """An answer fits the open pause when the NLU carries the awaited slot
    and no other flow's intent rides along with it (Graph shape, step 3).
    """
    slots = nlu.slots
    awaits = pending["awaiting_slot"]
    if awaits == "card_hint":
        carries = slots.card_hint is not None
    elif awaits == "block_kind":
        carries = slots.block_kind is not None
    elif awaits in _CONFIRMATION_SLOTS:
        carries = "affirm" in nlu.intents or "deny" in nlu.intents
    else:
        carries = False
    return carries and not _has_other_flow_intent(nlu, pending)


def _has_other_flow_intent(nlu: NLUResult, pending: Pending) -> bool:
    """True when a registered flow intent other than the pending flow's own
    rides along with this turn's answer (D20, P1's neighbour: such a turn
    doesn't "fit" -- `route` sends it to `enqueue` instead so P1 can replace
    the paused flow).
    """
    for intent in nlu.intents:
        flow = _INTENT_NODES.get(intent)
        if flow is not None and flow != pending["flow"]:
            return True
    return False
