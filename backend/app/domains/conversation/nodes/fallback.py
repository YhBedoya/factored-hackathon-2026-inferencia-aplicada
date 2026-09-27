"""Fixed-template reply when nothing else can answer this turn (D15).

Reached from `route` (`state["nlu"]` is `None`, e.g. `LLMUnavailable`/
`LLMInvalidOutput` in `understand`) or from `card_info` after it sets
`escalation_reason` (`clarification_exhausted`, `tool_unavailable`, or the
mid-card `NoCards` outcome -- see the state file's T6/T10 entries). No LLM
call: `escalation_reason == "no_cards"` gets the dedicated `no_cards`
template (T8), everything else gets the generic `fallback` text. The
handoff half of R11 (routing to a human) comes with D4.
"""

from typing import Any

from app.domains.conversation.graph import GraphState
from app.domains.conversation.templates import TemplateKind, get_template

__all__ = ["fallback"]


def fallback(state: GraphState) -> dict[str, Any]:
    """Fixed ES/PT fallback (or no-cards) template, no LLM call (D15)."""
    language = state.get("language", "es")
    kind: TemplateKind = "no_cards" if state.get("escalation_reason") == "no_cards" else "fallback"
    return {"reply": get_template(kind, language)}
