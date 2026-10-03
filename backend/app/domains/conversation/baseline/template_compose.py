"""The baseline's four LLM-free node swaps (D17, D30): no call ever leaves here.

`understand` wraps `keyword_nlu`; `compose` fills the D12 `goal_*` template
through `compose`'s own `_format_fact` path; `handoff_summary` uses the
fixed per-reason text; `abstain` fills `abstain_fallback` directly.
"""

from typing import Any

from langchain_core.runnables import RunnableConfig

from app.domains.conversation.baseline.keyword_nlu import keyword_nlu
from app.domains.conversation.graph import GraphState
from app.domains.conversation.nodes.abstain import make_abstain
from app.domains.conversation.nodes.compose import (
    _HIDDEN_KEYS,
    Goal,
    _card_goal,
    _current_intent,
    _fill_goal_template,
    append_next_step_offer,
)
from app.domains.conversation.nodes.handoff_summary import _fallback
from app.domains.conversation.templates import get_template
from app.domains.policy.escalation import load_escalation_policy, resolve_escalation

__all__ = [
    "baseline_abstain",
    "baseline_compose",
    "baseline_handoff_summary",
    "baseline_understand",
]

baseline_abstain = make_abstain(llm_wording=False)


async def baseline_understand(state: GraphState, config: RunnableConfig) -> dict[str, Any]:
    """`keyword_nlu` in `understand`'s update shape: `nlu` and the reply language."""
    previous_language = state.get("language", "es")
    nlu = keyword_nlu(state["user_text"], previous_language)
    language = nlu.language if nlu.language in ("es", "pt") else previous_language
    return {"nlu": nlu, "language": language}


async def baseline_compose(state: GraphState, config: RunnableConfig) -> dict[str, Any]:
    """The turn's `goal_*` template filled from its facts; grounding is always `template`."""
    facts = list(state.get("facts", []))
    facts_by_key = {fact.key: fact for fact in facts}
    offered_keys = [key for key in facts_by_key if key not in _HIDDEN_KEYS]
    card_kind = facts_by_key.get("card_kind")
    is_debit = card_kind is not None and card_kind.value == "debit"
    goal: Goal = _card_goal(_current_intent(state), is_debit=is_debit)
    language = state["language"]
    text = _fill_goal_template(goal, offered_keys, facts_by_key, language, state["country"])
    segments = [text]
    if "min_payment" in facts_by_key:
        segments.append(get_template("synthetic_footnote", language))
    if "read_only_note" in facts_by_key:
        segments.append(get_template("read_only_note", language))
    segments = append_next_step_offer(segments, facts_by_key, language)
    return {"segments": segments, "grounding": "template"}


async def baseline_handoff_summary(state: GraphState, config: RunnableConfig) -> dict[str, Any]:
    """The fixed per-reason `request` text, resolved like `handoff_summary` does."""
    language = state["language"]
    nlu = state.get("nlu")
    pending = state.get("pending")
    resolution = resolve_escalation(
        load_escalation_policy(),
        reason=state.get("escalation_reason"),
        queue=state.get("handoff_queue"),
        pending_flow=pending["flow"] if pending else None,
        intents=list(nlu.intents) if nlu is not None else [],
        text=state.get("user_text", ""),
    )
    return {"handoff_request": _fallback(resolution.reason if resolution else None, language)}
