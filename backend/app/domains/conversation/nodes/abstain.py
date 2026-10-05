"""Structured abstain for out-of-market / out-of-scope requests (ADR-026, D18).

Never a bare topic list: code builds four already-localized facts from
`policies/scope.yaml` and the NLU `topic` (topic label, why this chat can't
do it, the closest supported action, an offer of a person), and `compose`
phrases them. The closest action and the human offer also go out as
quick-reply chips. A pending flow is left exactly as it is: this node never
touches `pending`, so the flow's own question resumes on the next turn.
Reads no bank or handoff tools -- only policy and the fixed texts below.
"""

import re
from collections.abc import Awaitable, Callable
from typing import Any

from langchain_core.runnables import RunnableConfig

from app.core.llm import LLMClient
from app.domains.conversation.fact_values import record
from app.domains.conversation.graph import GraphState
from app.domains.conversation.nodes.compose import compose_reply_flagged
from app.domains.conversation.state import Fact
from app.domains.conversation.templates import Language, get_template, template_variants
from app.domains.conversation.ui import PickerOption, QuickRepliesEvent, QuickRepliesPayload
from app.domains.policy.registry import get_policies

__all__ = ["abstain", "card_request_unavailable_reply", "make_abstain"]

_SOURCE = "policies/scope.yaml"

_TOPIC_LABELS: dict[str, dict[Language, str]] = {
    "loans": {"es": "préstamos", "pt": "empréstimos"},
    "accounts": {"es": "cuentas bancarias", "pt": "contas bancárias"},
    "investments": {"es": "inversiones", "pt": "investimentos"},
    "insurance": {"es": "seguros", "pt": "seguros"},
    "transfers": {"es": "transferencias", "pt": "transferências"},
    "pix_boleto": {"es": "Pix y boletos", "pt": "Pix e boletos"},
    "other": {"es": "eso", "pt": "isso"},
}

_REASONS: dict[str, dict[Language, str]] = {
    "market_not_served": {
        "es": "Swip no opera ese servicio en tu país.",
        "pt": "A Swip não opera esse serviço no seu país.",
    },
    "not_card_product": {
        "es": "Este chat atiende tus tarjetas.",
        "pt": "Este chat cuida dos seus cartões.",
    },
    "outside_card_support": {
        "es": "Está fuera de lo que puedo resolver en este chat de tarjetas.",
        "pt": "Está fora do que consigo resolver neste chat de cartões.",
    },
}

# Intent -> the chip label and the sentence offering it.
_ACTION_LABELS: dict[str, dict[Language, str]] = {
    "card_status": {"es": "Ver el estado de tu tarjeta", "pt": "Ver o status do seu cartão"},
    "balance_due": {"es": "Ver cuánto debes en tu tarjeta", "pt": "Ver quanto você deve no cartão"},
}

_HUMAN_OFFERS: dict[Language, str] = {
    "es": "Hablar con una persona",
    "pt": "Falar com uma pessoa",
}


def _closest_action(intents: list[str], language: Language) -> str:
    for intent in intents:
        label = _ACTION_LABELS.get(intent)
        if label is not None:
            return label[language]
    return ""


def card_request_unavailable_reply(language: Language) -> dict[str, Any]:
    """The fixed "can't handle card requests here" reply plus the human chip (D3, C7).

    One builder for every path that cannot serve an open/close request (the
    pipeline's `new_card` topic, the agent with its flag off or the LLM down):
    no LLM call, no write.
    """
    options = [PickerOption(label=_HUMAN_OFFERS[language])]
    return {
        "segments": [get_template("card_request_unavailable", language)],
        "ui": [
            QuickRepliesEvent(
                kind="quick_replies",
                payload=QuickRepliesPayload(slot="abstain", options=options),
            )
        ],
    }


def make_abstain(
    *, llm_wording: bool = True, legacy_new_card: bool = False
) -> Callable[..., Awaitable[dict[str, Any]]]:
    """The abstain node; `llm_wording=False` is the baseline's swap (D17, D30).

    `legacy_new_card=True` keeps the baseline's old "new card not available"
    reply for topic `new_card` (R-d); the proposed node answers with
    `card_request_unavailable` and a human chip.

    Only the wording step differs: the baseline fills `abstain_fallback`
    directly and never touches the LLM. Facts, chips and `pending` are shared.
    """

    async def node(state: GraphState, config: RunnableConfig) -> dict[str, Any]:
        result, _ = await _abstain(
            state, config, llm_wording=llm_wording, legacy_new_card=legacy_new_card
        )
        return result

    return node


async def abstain(state: GraphState, config: RunnableConfig) -> dict[str, Any]:
    """Compose the four-part abstain reply and offer the chips (ADR-026).

    With a classifier loaded, a degraded turn takes the baseline wording (D4).
    When its own LLM call fails, the reply is the usual fallback and the turn
    is marked `degraded` (D2).
    """
    if config["configurable"].get("classifier") is not None and state.get("degraded"):
        # Lazy import: the baseline module imports this one.
        from app.domains.conversation.baseline.template_compose import baseline_abstain

        return await baseline_abstain(state, config)
    result, llm_failed = await _abstain(state, config, llm_wording=True)
    if llm_failed and config["configurable"].get("classifier") is not None:
        result["degraded"] = True
    return result


async def _abstain(
    state: GraphState, config: RunnableConfig, *, llm_wording: bool, legacy_new_card: bool = False
) -> tuple[dict[str, Any], bool]:
    """The reply update and whether the wording call raised `LLMError`."""
    language = state["language"]
    nlu = state.get("nlu")
    topic = nlu.slots.topic if nlu is not None and nlu.slots.topic else "other"

    if topic == "new_card":
        # Not a scope topic any more (scope v3): fixed wording, no compose call.
        if legacy_new_card:
            return {"segments": [get_template("new_card_not_available", language)], "ui": []}, False
        return card_request_unavailable_reply(language), False

    entry = get_policies().scope.topics[topic]

    topic_label = _TOPIC_LABELS[topic][language]
    reason = _REASONS[entry.reason_key][language]
    closest_action = _closest_action(entry.closest_intents, language)
    # A topic a person cannot help with (offer_human false) gets no human fact or chip.
    human_offer = _HUMAN_OFFERS[language] if entry.offer_human else ""

    values = {
        "topic_label": topic_label,
        "abstain_reason": reason,
        "closest_action": closest_action,
        "human_offer": human_offer,
    }
    record(*(v for v in values.values() if v))
    # An absent closest action is left out, so the composer never offers a
    # placeholder that would fill as an empty string.
    facts = [Fact(key=k, value=v, source=_SOURCE) for k, v in values.items() if v]
    text = get_template("fallback", language)
    llm_failed = False
    if llm_wording:
        llm: LLMClient = config["configurable"]["llm"]
        text, llm_failed = await compose_reply_flagged(
            llm, language=language, country=state["country"], goal="abstain", facts=facts
        )
    if text in template_variants("fallback", language):
        # The closest action and the human offer are chips, not words in the text.
        text = get_template("abstain_fallback", language).format(
            topic_label=topic_label, reason=reason
        )
        text = re.sub(r"\s+", " ", text).strip()

    labels = [closest_action] if closest_action else []
    if human_offer:
        labels.append(human_offer)
    if not labels:
        return {"segments": [text], "ui": []}, llm_failed
    options = [PickerOption(label=label) for label in labels]
    update = {
        "segments": [text],
        "ui": [
            QuickRepliesEvent(
                kind="quick_replies",
                payload=QuickRepliesPayload(slot="abstain", options=options),
            )
        ],
    }
    return update, llm_failed
