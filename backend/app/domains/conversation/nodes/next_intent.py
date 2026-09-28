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

from app.domains.conversation.graph import _MANAGEMENT_INTENTS, GraphState
from app.domains.conversation.state import RESET_FACTS

__all__ = ["enqueue", "finish", "next_intent"]


async def enqueue(state: GraphState, config: RunnableConfig) -> dict[str, Any]:
    """Queue this turn's card-action intents; apply P1 on an open pause (D20)."""
    nlu = state.get("nlu")
    non_management = [] if nlu is None else [i for i in nlu.intents if i not in _MANAGEMENT_INTENTS]
    update: dict[str, Any] = {"intent_queue": non_management}

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
    if remaining:
        update["facts"] = RESET_FACTS
    return update


def finish(state: GraphState) -> dict[str, Any]:
    """Join this turn's `segments` into the single `reply` output channel (D8)."""
    return {"reply": "\n\n".join(state.get("segments") or [])}
