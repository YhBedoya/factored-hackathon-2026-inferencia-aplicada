"""Fixed-template reply for routes with no handler yet (D14).

`route` sends here for the three "we don't do that at all" NLU statuses
(`out_of_market`, `out_of_scope`, `injection_suspected`) and for any intent
other than `card_status`, including a lone `greeting`. `route` already
guarantees `state["nlu"]` is not `None` by the time this node runs (a
missing NLU result goes to `fallback` instead), so the only decision left
here is which of the four templates matches `nlu.status`; anything else
falls through to the generic `unsupported_intent` text. No LLM call (D14):
D4 (G10) replaces this with structured abstain.
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
    return {"reply": get_template(kind, language)}
