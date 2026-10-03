"""The raw NLU call: one turn's text in, one `NLUResult` out (`02` §2).

`run_nlu` takes exactly what the prompt needs as arguments -- it does not
read `TurnState` or any graph config. `understand` below is the graph-level
wrapper: it reads `state["user_text"]`/`state["pending"]`/`state["country"]`
and `config["configurable"]["llm"]`, and writes `state["nlu"]`/
`state["language"]` (D8, D16).
"""

from typing import Any

from langchain_core.runnables import RunnableConfig

from app.core.llm import LLMClient, LLMError, PromptRef
from app.domains.conversation.classifier import IntentClassifier
from app.domains.conversation.graph import GraphState
from app.domains.conversation.nodes.route import _answer_fits
from app.domains.conversation.prompts import load_prompt
from app.domains.conversation.schemas import NLUResult
from app.domains.conversation.state import Pending

__all__ = ["run_nlu", "understand"]

_PROMPT = PromptRef("nlu", 5)
# D8: the second ambiguous turn in a row hands off (ADR-004: escalate after 2 failures).
_MAX_REPHRASE_FAILURES = 2


async def run_nlu(
    llm: LLMClient, text: str, *, pending: Pending | None, country: str | None
) -> NLUResult:
    """Classify one turn: intents, status and slots (`02` §2, D16, D18).

    The user's message is wrapped in a delimited block in the user message
    (R6: even though this is the customer's own text and not tool output,
    it never blends into the system prompt as free-form instructions). No
    tool output ever reaches this node (`02` §2: "No tool output is ever
    passed to this node").
    """
    system = load_prompt(_PROMPT)
    user = _build_user_message(text, pending=pending, country=country)
    return await llm.structured(
        step="nlu", prompt=_PROMPT, system=system, user=user, schema=NLUResult
    )


def _build_user_message(text: str, *, pending: Pending | None, country: str | None) -> str:
    """Country and the pending question as plain context lines, then the
    delimited user message (see the prompt's "La pregunta pendiente" section).
    """
    lines = [f"Pais: {country or 'desconocido'}"]
    if pending is None:
        lines.append("Pregunta pendiente: ninguna.")
    else:
        lines.append(
            f"Pregunta pendiente: el flujo '{pending['flow']}' (nodo "
            f"'{pending['node']}') espera el slot '{pending['awaiting_slot']}'."
        )
    lines.append("Mensaje del cliente:")
    lines.append("```")
    lines.append(text)
    lines.append("```")
    return "\n".join(lines)


async def understand(state: GraphState, config: RunnableConfig) -> dict[str, Any]:
    """Graph wrapper around `run_nlu`: writes `nlu` and the reply language (D16).

    With a classifier loaded (spec D2, ADR-032) the turn can run LLM-free: when
    `load_session` already marked it `degraded` (kill switch) the classifier
    answers directly, and on `LLMError` it answers instead of the handoff, with
    `"degraded": True` so the later nodes swap to their baselines too. With no
    classifier, an `LLMError` writes `nlu` as `None` so `route` falls back with
    no crash, exactly as before.
    Either way the turn still needs a reply language: `nlu.language` when
    it's `es`/`pt`, otherwise (a `mixed` or `other` result, or no result at
    all) the previous `state["language"]`, or `es` on the very first turn (D16).
    """
    configurable = config["configurable"]
    classifier: IntentClassifier | None = configurable.get("classifier")
    previous_language = state.get("language", "es")
    if state.get("degraded") and classifier is not None:
        return _classify(classifier, state, previous_language, degraded=False)
    llm: LLMClient = configurable["llm"]
    try:
        nlu = await run_nlu(
            llm, state["user_text"], pending=state.get("pending"), country=state.get("country")
        )
    except LLMError:
        if classifier is not None:
            return _classify(classifier, state, previous_language, degraded=True)
        return {"nlu": None, "language": previous_language, "escalation_reason": "llm_unavailable"}

    language = nlu.language if nlu.language in ("es", "pt") else previous_language
    return {"nlu": nlu, "language": language}


def _classify(
    classifier: IntentClassifier, state: GraphState, previous_language: str, *, degraded: bool
) -> dict[str, Any]:
    """The no-LLM `understand`: the local classifier plus D8's ambiguity counter.

    An `ambiguous` result with no `clarification` and no fitting pending answer
    counts as a failure; the second in a row ends in `clarification_exhausted`
    (`route` then hands off). Any other result resets the counter.
    """
    pending = state.get("pending")
    nlu = classifier.predict(
        state["user_text"],
        pending=pending,
        country=state.get("country"),
        previous_language=previous_language,
    )
    language = nlu.language if nlu.language in ("es", "pt") else previous_language
    update: dict[str, Any] = {"nlu": nlu, "language": language, "clarification_failures": 0}
    if degraded:
        update["degraded"] = True
    if nlu.status == "ambiguous" and nlu.clarification is None and not _answer_fits(nlu, pending):
        failures = state.get("clarification_failures", 0) + 1
        if failures >= _MAX_REPHRASE_FAILURES:
            update["escalation_reason"] = "clarification_exhausted"
        else:
            update["clarification_failures"] = failures
    return update
