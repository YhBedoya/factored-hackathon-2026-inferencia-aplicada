"""Fixed-template reply when nothing else can answer this turn (D15).

Reached from `route` (`state["nlu"]` is `None`, e.g. `LLMUnavailable`/
`LLMInvalidOutput` in `understand`), from `_entry` under `LLM_DISABLED`, from
`compose` after an `LLMError`, or from a flow after it sets
`escalation_reason` (`clarification_exhausted`, `tool_failure`,
`llm_unavailable`, or the mid-card `NoCards` outcome). No LLM call: each
known `escalation_reason` gets its own Cardy template (`no_cards`,
`clarification_exhausted`, `failure_handoff`), anything else gets the
generic `fallback` text. The two failure reasons then continue to
`handoff_summary` -> `handoff` (D8, R11); `failure_handoff_after_action` is
used instead when an action was verified earlier in this same turn (D9).
"""

from typing import Any

from app.domains.conversation.graph import GraphState
from app.domains.conversation.templates import TemplateKind, get_template

__all__ = ["fallback"]

_REASON_TEMPLATES: dict[str, TemplateKind] = {
    "no_cards": "no_cards",
    "tool_failure": "failure_handoff",
    "llm_unavailable": "failure_handoff",
    "clarification_exhausted": "clarification_exhausted",
}

_FAILURE_REASONS = frozenset({"tool_failure", "llm_unavailable"})


def _verified_this_turn(state: GraphState) -> bool:
    """True when an `ActionResult` with `verified=True` was appended this turn (D9)."""
    actions = state.get("actions", [])
    return any(a.verified for a in actions[state.get("actions_at_turn_start", 0) :])


def fallback(state: GraphState) -> dict[str, Any]:
    """Fixed ES/PT template for the escalation reason, no LLM call (D15)."""
    language = state.get("language", "es")
    reason = state.get("escalation_reason") or ""
    kind = _REASON_TEMPLATES.get(reason, "fallback")
    # A failed write may still have been applied by the bank: never say "no change".
    if reason in _FAILURE_REASONS and (_verified_this_turn(state) or state.get("write_failed")):
        kind = "failure_handoff_after_action"
    return {"segments": [get_template(kind, language)]}
