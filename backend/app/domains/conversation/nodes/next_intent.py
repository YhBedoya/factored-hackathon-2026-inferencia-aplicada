"""The intent queue's plumbing: `enqueue`, `next_intent`, `finish` (B3, D20).

`enqueue` is the conditional-edge target `route` picks for a fresh (or
replacing) card action (Graph shape step 5): it turns this turn's
non-management intents into `intent_queue`, in message order, and applies P1
when a flow was already paused on something else -- cancel its open plan
(if any), then clear `pending`/`confirmation_token_id`/`clarification_failures`
so the new queue starts from a clean pause state. `next_intent` pops the
intent this turn's flow node just answered and, when another is still
queued, resets `facts` (Q3) so `compose` never blends one intent's facts
into the next one's segment. `finish` joins `segments` into the one `reply`
output channel.

No LLM: this module must never import `app.core.llm` (R6) -- `enqueue`'s
only side effect is `bank_write_tools.cancel_plan`, read off
`config["configurable"]` the same way every other write-flow call will be,
never a raw `BankWriteTools` (D5).
"""

from typing import Any

from langchain_core.runnables import RunnableConfig

from app.domains.conversation.flows.actions import closing
from app.domains.conversation.graph import _INTENT_NODES, _MANAGEMENT_INTENTS, GraphState
from app.domains.conversation.state import RESET_FACTS
from app.domains.conversation.templates import TemplateKind, template_variants
from app.domains.policy.registry import get_policies

__all__ = ["enqueue", "finish", "next_intent"]


def _degraded_handoff(state: GraphState, head: str | None) -> bool:
    """True when the LLM is down and the queue head must hand off (D7, ADR-032)."""
    return (
        bool(state.get("degraded"))
        and head is not None
        and head in get_policies().escalation.degraded_handoff_intents
    )


async def enqueue(state: GraphState, config: RunnableConfig) -> dict[str, Any]:
    """Queue this turn's card-action intents; apply P1 on an open pause (D20)."""
    nlu = state.get("nlu")
    non_management = [] if nlu is None else [i for i in nlu.intents if i not in _MANAGEMENT_INTENTS]
    update: dict[str, Any] = {"intent_queue": non_management}
    if _degraded_handoff(state, non_management[0] if non_management else None):
        update["escalation_reason"] = "llm_unavailable"

    pending = state.get("pending")
    if pending is not None:
        token_id = state.get("confirmation_token_id")
        bank_write_tools = config["configurable"].get("bank_write_tools")
        if bank_write_tools is not None and token_id is not None:
            await bank_write_tools.cancel_plan(token_id)
        update["pending"] = None
        update["confirmation_token_id"] = None
        update["clarification_failures"] = 0
    return update


def next_intent(state: GraphState) -> dict[str, Any]:
    """Pop the intent this turn's flow node just answered (D20).

    `facts` is reset only when another intent is still queued: an empty
    queue means this is the last (or only) segment, and `test_graph`'s
    snapshot relies on that turn's facts still being there once the graph
    reaches `finish`.
    """
    queue = list(state.get("intent_queue") or [])
    if not queue:
        return {}
    remaining = queue[1:]
    update: dict[str, Any] = {"intent_queue": remaining}
    if _degraded_handoff(state, remaining[0] if remaining else None):
        update["escalation_reason"] = "llm_unavailable"
    if remaining:
        update["facts"] = RESET_FACTS
    elif queue[0] in _INTENT_NODES and _closing_allowed({**state, "intent_queue": []}):
        # The last queued flow just answered (a query, a cancel, a declined
        # offer) and left nothing pending: close the flow with the question.
        update.update(_closing_update(state))
    return update


def finish(state: GraphState) -> dict[str, Any]:
    """Join this turn's `segments` into the single `reply` output channel (D8).

    Also appends the reply to `history` (naturalidad-cardy D3). It carries
    tokens, not values, until the runner unmasks it. No trimming here:
    `summarize` folds the overflow on the next typed turn. Human mode never
    gets a bot reply to remember.
    """
    update: dict[str, Any] = {}
    segments = list(state.get("segments") or [])
    if _owes_closing(state):
        # A verified action ran earlier this turn but its own closing was held
        # back while intents were queued (`with_closing`); the queue has drained.
        update = _closing_update(state)
        segments += update["segments"]
    reply = "\n\n".join(segments)
    update["reply"] = reply
    if reply and state.get("mode") != "human":
        update["history"] = [*(state.get("history") or []), {"role": "cardy", "text": reply}]
    return update


# Replies that already ask the customer for something (no pause) or refuse an
# access attempt: a cheerful "anything else?" after them would be wrong.
_NO_CLOSING_KINDS: tuple[TemplateKind, ...] = ("tx_search_ask_criterion", "injection_suspected")


def _closing_allowed(state: GraphState) -> bool:
    """The skips shared by every closing: nothing else is waiting on the customer
    and the reply doesn't already end by asking something.
    """
    if state.get("mode") == "human" or state.get("intent_queue"):
        return False
    if state.get("pending") is not None:
        return False
    if state.get("escalation_reason") is not None or state.get("handoff_queue") is not None:
        return False
    segments = state.get("segments") or []
    if not segments:
        return False
    language = state["language"]
    if any(segments[-1] in template_variants(kind, language) for kind in _NO_CLOSING_KINDS):
        return False
    # A chip row means the reply already asked (the human offer, abstain).
    return not any(getattr(event, "kind", None) == "quick_replies" for event in state.get("ui", []))


def _closing_update(state: GraphState) -> dict[str, Any]:
    """`closing(...)` as a state update that keeps this turn's other ui events."""
    extra = closing(state["language"])
    return {
        "segments": extra["segments"],
        "pending": extra["pending"],
        "ui": [*state.get("ui", []), *extra["ui"]],
    }


def _owes_closing(state: GraphState) -> bool:
    """True when a verified action ran this turn but its own closing was held
    back while intents were queued (`with_closing`); R3: no verified action,
    no closing from here.
    """
    if not _closing_allowed(state):
        return False
    actions = state.get("actions", [])[state.get("actions_at_turn_start", 0) :]
    return any(a.verified for a in actions)
