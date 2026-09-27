"""Turn start: bind the session's `customer_id`, then reset per-turn state (D8, D9).

This is the only node that reads `config["configurable"]["session"]` (the
`ToolContext` the sandbox/API built) and `["bank_tools"]` (the bound
`FakeBank`). `customer_id` comes from the session alone -- never from
`user_text`, NLU output or any other state field (R1) -- and is written
through the existing `bind_once` reducer (`state.py`): this node never calls
`bind_once` itself, it just returns the value and lets the graph's
`Annotated[str, bind_once]` merge apply the same first-write-wins, no-op-on-
repeat, raise-on-change semantics as before.

`facts`, `nlu` and `escalation_reason` are reset here at the start of every
turn (Q3) so a later `compose` node only ever sees facts a flow wrote this
turn, not ones left over from an earlier one.
"""

from typing import Any

from langchain_core.runnables import RunnableConfig

from app.domains.conversation.graph import GraphState
from app.domains.conversation.state import RESET_FACTS
from app.domains.conversation.tools import BankReadTools, ToolContext

__all__ = ["load_session"]


async def load_session(state: GraphState, config: RunnableConfig) -> dict[str, Any]:
    """Bind `customer_id`/`country` from the session and reset per-turn state."""
    configurable = config["configurable"]
    session: ToolContext = configurable["session"]
    bank_tools: BankReadTools = configurable["bank_tools"]

    profile = await bank_tools.get_profile()
    return {
        "customer_id": session.customer_id,
        "country": profile.country,
        "facts": RESET_FACTS,
        "nlu": None,
        "escalation_reason": None,
    }
