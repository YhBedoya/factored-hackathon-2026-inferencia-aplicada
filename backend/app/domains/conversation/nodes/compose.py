"""Fills one short reply from fact keys, values formatted in code (D10, R4, R6).

`compose_reply` takes exactly what the prompt needs as arguments -- it does
not read `TurnState` or any graph config (see `understand.run_nlu` for the
same pattern). The LLM only ever sees fact **keys** inside a fenced data
block in the user message; no money, date or card-number *value* is ever
sent as text. A draft that names a placeholder this turn did not offer, or
writes a raw digit outside a placeholder is rejected in code (D11): the LLM
gets one more call with the reason, then the goal's fact template fills the
reply. An `LLMError` from the call itself still gives the fixed `fallback`.

`compose` below is the graph-level wrapper: it picks the turn's goal from
this turn's intent and passes `state["facts"]` -- this turn's only, thanks
to `load_session`'s per-turn reset (Q3) -- through to `compose_reply`.
"""

import re
from datetime import date
from decimal import Decimal
from typing import Any, Literal, cast

from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, ConfigDict

from app.core.llm import LLMClient, LLMError, PromptRef
from app.core.pii import find_pii
from app.domains.conversation.fact_values import record
from app.domains.conversation.graph import GraphState
from app.domains.conversation.prompts import load_prompt
from app.domains.conversation.schemas import Intent
from app.domains.conversation.state import Fact
from app.domains.conversation.templates import Language, TemplateKind, get_template
from app.domains.localization import (
    format_date,
    format_days,
    format_money,
    kind_label,
    mask_card,
    mxn_estimate,
    status_label,
)
from app.domains.localization.schemas import FxRate

__all__ = ["ComposeDraft", "compose", "compose_checked", "compose_reply"]

_PROMPT = PromptRef("compose", 6)
_PLACEHOLDER = re.compile(r"\{(\w+)\}")

Grounding = Literal["ok", "regenerated", "template"]
_GOAL_TEMPLATES: dict[str, TemplateKind] = {
    "card_status": "goal_card_status",
    "balance_due": "goal_balance_due",
    "decline_explain": "goal_decline_explain",
}

# Words that belong to one language only (shared ones like `para`, `que`, `esta` are left out).
_ES_WORDS = frozenset(
    "el los las tu tus una del con es y en por se puedes tarjeta hoy vence saldo pago minimo "
    "mínimo estimado actual hay".split()
)
_PT_WORDS = frozenset(
    "os as seu sua seus suas uma do da dos com é e em você voce não nao cartão cartao hoje "
    "saldo pagamento mínimo atual há".split()
)

Goal = Literal["card_status", "balance_due", "abstain", "decline_explain"]
Country = Literal["MX", "CO", "AR"]

# Facts a flow writes for code's own use (formatting, footnotes) but that
# `compose`'s draft never offers as a `{placeholder}` (D19, this card's B1):
# `currency` only picks a money format; `fx_rate`/`fx_as_of` only feed the
# MXN-estimate suffix; `read_only_note` is always its own fixed template,
# appended after the draft, never woven into it by the LLM.
_HIDDEN_KEYS = frozenset({"currency", "fx_rate", "fx_as_of", "read_only_note"})

# D5-B D4, D6: `policies/decline_codes.yaml`'s `cause_key`/`next_step_key`
# values, mapped to their own fixed ES/PT template (`templates.py`) -- the
# same "code picks the fixed label, the LLM only places it" shape
# `flows/unrecognized_charge.py`'s `_QUESTION_TEMPLATES` sets for
# `disputes.yaml`'s question ids.
_DECLINE_CAUSE_TEMPLATES: dict[str, TemplateKind] = {
    "insufficient_funds": "decline_cause_insufficient_funds",
    "invalid_card_number": "decline_cause_invalid_card_number",
    "do_not_honor": "decline_cause_do_not_honor",
    "expired_card": "decline_cause_expired_card",
}
_DECLINE_NEXT_TEMPLATES: dict[str, TemplateKind] = {
    "pay_or_use_other_card": "decline_next_pay_or_use_other_card",
    "check_card_number": "decline_next_check_card_number",
    "contact_or_retry": "decline_next_contact_or_retry",
    "offer_replacement": "decline_next_offer_replacement",
}


class ComposeDraft(BaseModel):
    """The compose call's structured output (D10, §"Contracts")."""

    model_config = ConfigDict(extra="forbid")

    text: str


async def compose_reply(
    llm: LLMClient, *, language: Language, country: Country, goal: Goal, facts: list[Fact]
) -> str:
    """`compose_checked`'s text alone, for callers that don't need the outcome."""
    text, _ = await compose_checked(llm, language=language, country=country, goal=goal, facts=facts)
    return text


async def compose_checked(
    llm: LLMClient, *, language: Language, country: Country, goal: Goal, facts: list[Fact]
) -> tuple[str, Grounding]:
    """Write one short reply from `facts` for `goal`, in `language` (D10, D11).

    Only fact keys (never values) reach the LLM. `_HIDDEN_KEYS` are never
    offered as placeholders -- they only drive formatting in code. A draft
    that fails `_draft_problem` gets one more call with the reason; a second
    failure fills the goal's fact template (D12). `LLMError` gives `fallback`.
    """
    facts_by_key = {fact.key: fact for fact in facts}
    offered_keys = [key for key in facts_by_key if key not in _HIDDEN_KEYS]

    system = load_prompt(_PROMPT)
    user = _build_user_message(language=language, goal=goal, offered_keys=offered_keys)
    problem: str | None = None
    for attempt in range(2):
        message = user if problem is None else f"{user}\n\nCorrige: {problem}"
        try:
            draft = await llm.structured(
                step="compose", prompt=_PROMPT, system=system, user=message, schema=ComposeDraft
            )
        except LLMError:
            return get_template("fallback", language), "template"
        problem = _draft_problem(draft.text, offered_keys, language)
        if problem is None:
            text = _fill(draft.text, offered_keys, facts_by_key, language, country)
            return text, "ok" if attempt == 0 else "regenerated"

    return _fill_goal_template(goal, offered_keys, facts_by_key, language, country), "template"


def _fill(
    template: str,
    offered_keys: list[str],
    facts_by_key: dict[str, Fact],
    language: Language,
    country: Country,
) -> str:
    """Substitute the placeholders in `template` with values formatted in code (R4).

    Every value but the customer's name is noted for the grounding audit.
    """
    values = {
        key: _format_fact(key, facts_by_key, language=language, country=country)
        for key in offered_keys
    }
    used = {key: value for key, value in values.items() if f"{{{key}}}" in template}
    record(*(value for key, value in used.items() if key != "customer_name"))
    return _PLACEHOLDER.sub(lambda m: values[m.group(1)], template)


def _fill_goal_template(
    goal: Goal,
    offered_keys: list[str],
    facts_by_key: dict[str, Fact],
    language: Language,
    country: Country,
) -> str:
    """The goal's fixed fact template, filled in code (D12).

    A template whose keys this turn's facts don't all carry falls back to the
    generic `fallback`, never a half-filled sentence.
    """
    if goal == "abstain":
        template = get_template("abstain_fallback", language)
        if not all(key in offered_keys for key in ("topic_label", "abstain_reason", "human_offer")):
            return get_template("fallback", language)
        # The four-part template says `{reason}`; the fact is `abstain_reason`.
        template = template.replace("{reason}", "{abstain_reason}")
        if "closest_action" not in offered_keys:
            template = template.replace("{closest_action}", "")
        text = _fill(template, offered_keys, facts_by_key, language, country)
        return re.sub(r"\s+", " ", text).strip()
    template = get_template(_GOAL_TEMPLATES[goal], language)
    if any(key not in offered_keys for key in _PLACEHOLDER.findall(template)):
        return get_template("fallback", language)
    return _fill(template, offered_keys, facts_by_key, language, country)


def _draft_problem(text: str, offered_keys: list[str], language: Language) -> str | None:
    """Why `text` fails the grounding check, in D11's order; `None` when it passes."""
    if any(key not in offered_keys for key in _PLACEHOLDER.findall(text)):
        return "usaste una clave que no esta disponible"
    # Whatever is left after removing the well-formed `{key}` placeholders
    # must have no brace left either: a stray `{`/`}` (e.g. `{card_mask.upper}`,
    # `{card_mask[0]}`, `{card_mask:>99}`, `{}`) doesn't match `\w+` and so
    # escapes the check above, but str.format-style substitution on it would
    # run attribute/index access or a format spec on our own data (rejected
    # instead of ever reaching `str.format`, which we never call on the draft).
    residual = _PLACEHOLDER.sub("", text)
    if "{" in residual or "}" in residual:
        return "hay llaves que no son una {clave} valida"
    if any(char.isdigit() for char in residual):
        return "escribiste un numero; todo numero debe ir como {clave}"
    if find_pii(text):
        return "el texto contiene datos personales"
    if _wrong_language(residual, language):
        return f"la respuesta debe estar en idioma {language}"
    return None


def _wrong_language(text: str, language: Language) -> bool:
    """True when the stopword count clearly favors the other language.

    A draft with fewer than two hits for the other language is too short to
    judge and passes.
    """
    words = re.findall(r"[^\W\d_]+", text.lower())
    es = sum(word in _ES_WORDS for word in words)
    pt = sum(word in _PT_WORDS for word in words)
    own, other = (es, pt) if language == "es" else (pt, es)
    return other >= 2 and other > own


def _build_user_message(*, language: Language, goal: Goal, offered_keys: list[str]) -> str:
    """Language, goal and the offered fact **keys**, fenced as data (R6)."""
    lines = [
        f"Idioma de la respuesta: {language}",
        f"Objetivo: {goal}",
        "Claves de datos disponibles (usalas solo como {clave}; no hay valores aca):",
        "```",
        *offered_keys,
        "```",
    ]
    return "\n".join(lines)


def _format_fact(
    key: str, facts_by_key: dict[str, Fact], *, language: Language, country: Country
) -> str:
    """Format one fact's *value* per its key, using `domains/localization/` (R4)."""
    value = facts_by_key[key].value
    if key == "card_mask":
        return mask_card(cast(str, value))
    if key == "card_kind":
        return kind_label(cast(Literal["credit", "debit"], value), language)
    if key == "status":
        status = cast(Literal["Active", "Blocked", "Suspended", "Closed"], value)
        return status_label(status, language)
    if key in ("expiry", "due_date", "tx_date"):
        return format_date(cast(date, value))
    if key == "payment_overdue":
        return format_days(cast(int, value), language)
    if key in ("credit_limit", "available_credit", "current_balance", "min_payment", "amount"):
        return _money_fact(cast(Decimal, value), facts_by_key, language=language, country=country)
    # D5-B D4, D6: the policy's own key, rendered through its fixed template
    # -- the LLM never sees or picks what a decline code means.
    if key == "decline_cause":
        return get_template(_DECLINE_CAUSE_TEMPLATES[cast(str, value)], language)
    if key == "decline_next_step":
        return get_template(_DECLINE_NEXT_TEMPLATES[cast(str, value)], language)
    # `abstain` facts (ADR-026) and `merchant` (D5-B) arrive already
    # localized from the flow that wrote them.
    if key in (
        "card_options",
        "customer_name",
        "topic_label",
        "abstain_reason",
        "closest_action",
        "human_offer",
        "merchant",
    ):
        return str(value)
    raise ValueError(f"compose: no formatter for fact key {key!r}")


def _money_fact(
    value: Decimal, facts_by_key: dict[str, Fact], *, language: Language, country: Country
) -> str:
    """Format one money fact, then append the MXN estimate (D18) when this
    turn's facts carry `fx_rate`/`fx_as_of` (an MX card billed in USD).
    """
    currency_fact = facts_by_key.get("currency")
    currency = str(currency_fact.value) if currency_fact is not None else ""
    text = format_money(value, currency, country)
    fx_rate_fact = facts_by_key.get("fx_rate")
    fx_as_of_fact = facts_by_key.get("fx_as_of")
    if fx_rate_fact is not None and fx_as_of_fact is not None:
        fx = FxRate(
            source="USD",
            target="MXN",
            rate=cast(Decimal, fx_rate_fact.value),
            as_of=cast(date, fx_as_of_fact.value),
        )
        text += " " + mxn_estimate(value, fx, language)
    return text


def _current_intent(state: GraphState) -> Intent:
    """The intent this turn's flow node just answered (D20's queue head,
    same convention `flows/card_info.py` reads it by): the head of
    `intent_queue` is still this turn's intent, `next_intent` only pops it
    once this segment is done. An empty queue (a lone `card_status` never
    queued at all) falls back to `card_status`, same as the flow's own
    default.
    """
    queue = state.get("intent_queue") or []
    return queue[0] if queue else "card_status"


async def compose(state: GraphState, config: RunnableConfig) -> dict[str, Any]:
    """Graph wrapper around `compose_reply`: picks the goal, then fills the reply.

    The goal follows this turn's intent and the selected card's kind (D19,
    D2-B B1): `decline_explain` for that intent (D5-B, always -- there is no
    debit/credit split for it); otherwise `balance_due` for a credit card on
    `balance_due`, else `card_status` -- a debit card on `balance_due` gets
    its status described right after the fixed `credit_only` segment
    (`flows/card_info.py`). The "which card?" question never reaches here: it
    is a fixed per-action template the flow writes itself
    (`card_select.ask_which_card_text`, or the flow's own equivalent). `facts`
    are read straight off `state` -- the per-turn reset in `load_session`
    (Q3) is what makes that safe to pass through unfiltered. When the
    profile has a first name, it is offered as one more fact,
    `customer_name`: the LLM sees only the key and decides whether
    addressing the customer by name sounds natural (`docs/brand.md`); the
    value is filled in here, in code (R5).

    After the filled draft, `synthetic_footnote` is appended when this
    turn's facts carry `min_payment` (D5), and `read_only_note` when they
    carry that fact (D10/ADR-021) -- both fixed templates, never woven into
    the LLM's own draft. The filled text and any footnote are appended to
    `segments` (B3), never set as `reply` directly: `finish` is the only
    node that joins this turn's segments into the one reply the caller
    reads.
    """
    llm: LLMClient = config["configurable"]["llm"]
    facts = list(state.get("facts", []))
    facts_by_key = {fact.key: fact for fact in facts}

    intent = _current_intent(state)
    card_kind = facts_by_key.get("card_kind")
    is_debit = card_kind is not None and card_kind.value == "debit"
    goal: Goal
    if intent == "decline_explain":
        goal = "decline_explain"
    else:
        goal = "balance_due" if intent == "balance_due" and not is_debit else "card_status"

    customer_name = state.get("customer_name")
    if customer_name:
        facts.append(Fact(key="customer_name", value=customer_name, source="customers.get_profile"))
    text, grounding = await compose_checked(
        llm,
        language=state["language"],
        country=state["country"],
        goal=goal,
        facts=facts,
    )
    segments = [text]
    language = state["language"]
    if "min_payment" in facts_by_key:
        segments.append(get_template("synthetic_footnote", language))
    if "read_only_note" in facts_by_key:
        segments.append(get_template("read_only_note", language))
    return {"segments": segments, "grounding": grounding}
