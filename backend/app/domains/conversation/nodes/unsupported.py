"""Fixed-template reply for routes with no handler yet (D14, D20).

`route` sends here for the three "we don't do that at all" NLU statuses
(`out_of_market`, `out_of_scope`, `injection_suspected`), and `_dispatch`
sends here for any queued card-action intent with no flow yet (P3). A lone
`greeting` moved to `smalltalk` (B3): by the time a turn reaches this node
its intents are never management-only, so the only decision left here is
which of the three status templates matches `nlu.status`, or the generic
`unsupported_intent` text for anything else. No LLM call (D14): D4 (G10)
replaces this with structured abstain.
"""

from typing import Any

from app.domains.conversation.graph import GraphState
from app.domains.conversation.templates import TemplateKind, get_template

__all__ = ["unsupported"]

_STATUS_TEMPLATES: dict[str, TemplateKind] = {
    "out_of_market": "out_of_market",
    "out_of_scope": "out_of_scope",
    "injection_suspected": "injection_suspected",
}


def unsupported(state: GraphState) -> dict[str, Any]:
    """Fixed ES/PT template for the route kind, no LLM call (D14)."""
    language = state.get("language", "es")
    nlu = state.get("nlu")
    kind: TemplateKind = "unsupported_intent"
    if nlu is not None:
        kind = _STATUS_TEMPLATES.get(nlu.status, "unsupported_intent")
    return {"segments": [get_template(kind, language)]}
