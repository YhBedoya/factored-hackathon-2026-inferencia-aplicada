"""Turn start: bind the session's `customer_id`, then reset per-turn state (D8, D9, B3).

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
turn, not ones left over from an earlier one. `segments` (B3) gets the same
treatment through `RESET_SEGMENTS`, so `finish` only ever joins the
segments this turn's nodes actually wrote; `intent_segments` (the per-intent
record the runner audits) is reset the same way.

`ui` (D16) is reset to `[]` here too: it is a graph-local, non-checkpointed
channel, so a turn only ever reports the events an emitting node appended
this turn, never a stale one from an earlier turn.
"""

import re
from typing import Any, Literal

from langchain_core.runnables import RunnableConfig

from app.core.config import get_settings
from app.domains.conversation.graph import GraphState
from app.domains.conversation.state import RESET_FACTS, RESET_INTENT_SEGMENTS, RESET_SEGMENTS
from app.domains.conversation.tools import BankReadTools, ToolContext

__all__ = ["load_session"]

_PT_MARKERS = re.compile(
    r"[ãõç]|\b(?:não|nao|você|voce|cartão|cartao|obrigad[oa]|olá|quero|meu|minha|"
    r"fatura|pagamento)\b",
    re.IGNORECASE,
)


def _guess_language(text: str) -> Literal["es", "pt"]:
    """`pt` when the text carries a Portuguese-only marker, else `es` (pure, no LLM)."""
    return "pt" if _PT_MARKERS.search(text) else "es"


def _is_typed_turn(state: GraphState) -> bool:
    """A typed customer message worth remembering (naturalidad-cardy D3, A1).

    Button, pick and step-up turns arrive with empty text. The replacement
    address turn is skipped because its text is the raw new address, which the
    runner's vault cannot mask (R5). Human mode is not the bot's conversation.
    """
    pending = state.get("pending")
    return (
        bool(state.get("user_text"))
        and state.get("confirmation") is None
        and state.get("selection") is None
        and state.get("resume") is None
        and state.get("mode") != "human"
        and not (pending is not None and pending["awaiting_slot"] == "address")
    )


async def load_session(state: GraphState, config: RunnableConfig) -> dict[str, Any]:
    """Bind `customer_id`/`country`/`customer_name` from the session and reset per-turn state."""
    configurable = config["configurable"]
    session: ToolContext = configurable["session"]
    bank_tools: BankReadTools = configurable["bank_tools"]

    profile = await bank_tools.get_profile()
    # D10: the kill switch. Human mode is checked first by `_entry`, so a
    # human-owned conversation never sees the reason. With a classifier loaded
    # the switch means the degraded path (spec D2: zero LLM calls, no handoff);
    # without one the old `llm_unavailable` handoff stays. `actions_at_turn_start`
    # lets `fallback` tell an action verified this turn from an older one.
    kill_switch = get_settings().llm_disabled and state.get("mode") != "human"
    has_classifier = configurable.get("classifier") is not None
    degraded = kill_switch and has_classifier
    reason = "llm_unavailable" if kill_switch and not has_classifier else None
    update: dict[str, Any] = {
        "actions_at_turn_start": len(state.get("actions", [])),
        "write_failed": False,
        "suggestion_accepted": False,
        "asked_ui": None,
        "non_answer_counted": False,
        "customer_id": session.customer_id,
        "country": profile.country,
        "customer_name": profile.first_name,
        "facts": RESET_FACTS,
        "segments": RESET_SEGMENTS,
        "intent_segments": RESET_INTENT_SEGMENTS,
        "segment_deferred": None,
        "nlu": None,
        "escalation_reason": reason,
        "degraded": degraded,
        # `understand` never runs under the kill switch, and `handoff_summary`
        # reads `language`: keep the previous one; on a first turn detect it
        # in code from the customer's own text (no LLM).
        "language": state.get("language") or _guess_language(state.get("user_text", "")),
        "ui": [],
    }
    if _is_typed_turn(state):
        update["history"] = [
            *(state.get("history") or []),
            {"role": "customer", "text": state["user_text"]},
        ]
    return update
