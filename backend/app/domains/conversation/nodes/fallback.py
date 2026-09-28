"""Fixed-template reply when nothing else can answer this turn (D15).

Reached from `route` (`state["nlu"]` is `None`, e.g. `LLMUnavailable`/
`LLMInvalidOutput` in `understand`) or from `card_info` after it sets
`escalation_reason` (`clarification_exhausted`, `tool_unavailable`, or the
mid-card `NoCards` outcome -- see the state file's T6/T10 entries). No LLM
call: each known `escalation_reason` gets its own Cardy template
(`no_cards`, `tool_error`, `clarification_exhausted`), anything else gets the
generic `fallback` text. The handoff half of R11 (routing to a human) comes
with D4.
"""

from typing import Any

from app.domains.conversation.graph import GraphState
from app.domains.conversation.templates import TemplateKind, get_template

__all__ = ["fallback"]

_REASON_TEMPLATES: dict[str, TemplateKind] = {
    "no_cards": "no_cards",
    "tool_unavailable": "tool_error",
    "clarification_exhausted": "clarification_exhausted",
}


def fallback(state: GraphState) -> dict[str, Any]:
    """Fixed ES/PT template for the escalation reason, no LLM call (D15)."""
    language = state.get("language", "es")
    kind = _REASON_TEMPLATES.get(state.get("escalation_reason") or "", "fallback")
    return {"segments": [get_template(kind, language)]}
