"""Fixed-template reply for routes with no handler yet (D14, D20).

`route` sends here for `injection_suspected` and for a message in neither
Spanish nor Portuguese (`unsupported_language`), and `_dispatch` sends here for
any queued card-action intent with no flow yet (P3). `out_of_market` and
`out_of_scope` go to the `abstain` node (D13). Any other status gets the
generic `unsupported_intent` text. No LLM call (D14).
"""

from typing import Any

from langchain_core.runnables import RunnableConfig

from app.domains.audit.schemas import NullAuditRecorder
from app.domains.conversation.graph import GraphState
from app.domains.conversation.templates import TemplateKind, get_template
from app.domains.policy.registry import get_policies

__all__ = ["unsupported"]

_STATUS_TEMPLATES: dict[str, TemplateKind] = {"injection_suspected": "injection_suspected"}


async def unsupported(state: GraphState, config: RunnableConfig) -> dict[str, Any]:
    """Fixed ES/PT template for the route kind, no LLM call (D14).

    `injection_suspected` is the "someone else's data" attempt (D6): each one
    is audited `access_denied`; the attempt that reaches the policy threshold
    returns no segment and sets the escalation reason, so the handoff nodes
    write the reply.
    """
    language = state.get("language", "es")
    nlu = state.get("nlu")
    kind: TemplateKind = "unsupported_intent"
    if nlu is not None:
        kind = _STATUS_TEMPLATES.get(nlu.status, "unsupported_intent")
        if nlu.status != "injection_suspected" and nlu.language == "other":
            kind = "unsupported_language"
    if nlu is None or nlu.status != "injection_suspected":
        return {"segments": [get_template(kind, language)]}

    attempt = state.get("unauthorized_attempts", 0) + 1
    recorder = config["configurable"].get("audit") or NullAuditRecorder()
    await recorder.record("access_denied", {"source": "nlu", "attempt": attempt})
    threshold = get_policies().escalation.unauthorized_access.attempts_before_handoff
    if attempt >= threshold:
        return {"unauthorized_attempts": attempt, "escalation_reason": "unauthorized_access"}
    return {"segments": [get_template(kind, language)], "unauthorized_attempts": attempt}
