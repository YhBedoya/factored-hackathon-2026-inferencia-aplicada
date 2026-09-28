"""Fills one short reply from fact keys, values formatted in code (D10, R4, R6).

`compose_reply` takes exactly what the prompt needs as arguments -- it does
not read `TurnState` or any graph config (see `understand.run_nlu` for the
same pattern). The LLM only ever sees fact **keys** inside a fenced data
block in the user message; no money, date or card-number *value* is ever
sent as text. A draft that names a placeholder this turn did not offer, or
writes a raw digit outside a placeholder, is rejected in code -- never
repaired by calling the LLM again -- and replaced by the fixed `fallback`
template, same as an `LLMError` from the call itself (D10, D15).

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
from app.domains.conversation.graph import GraphState
from app.domains.conversation.prompts import load_prompt
from app.domains.conversation.schemas import Intent
from app.domains.conversation.state import Fact
from app.domains.conversation.templates import Language, get_template
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

__all__ = ["ComposeDraft", "compose", "compose_reply"]

_PROMPT = PromptRef("compose", 5)
_PLACEHOLDER = re.compile(r"\{(\w+)\}")

Goal = Literal["card_status", "balance_due", "abstain"]
Country = Literal["MX", "CO", "AR"]

# Facts a flow writes for code's own use (formatting, footnotes) but that
# `compose`'s draft never offers as a `{placeholder}` (D19, this card's B1):
# `currency` only picks a money format; `fx_rate`/`fx_as_of` only feed the
# MXN-estimate suffix; `read_only_note` is always its own fixed template,
# appended after the draft, never woven into it by the LLM.
_HIDDEN_KEYS = frozenset({"currency", "fx_rate", "fx_as_of", "read_only_note"})


class ComposeDraft(BaseModel):
    """The compose call's structured output (D10, §"Contracts")."""

    model_config = ConfigDict(extra="forbid")

    text: str


async def compose_reply(
    llm: LLMClient, *, language: Language, country: Country, goal: Goal, facts: list[Fact]
) -> str:
    """Write one short reply from `facts` for `goal`, in `language` (D10).

    Only fact keys (never values) reach the LLM. `_HIDDEN_KEYS` are never
    offered as placeholders -- they only drive formatting in code.
    """
    facts_by_key = {fact.key: fact for fact in facts}
    offered_keys = [key for key in facts_by_key if key not in _HIDDEN_KEYS]

    system = load_prompt(_PROMPT)
    user = _build_user_message(language=language, goal=goal, offered_keys=offered_keys)
    try:
        draft = await llm.structured(
            step="compose", prompt=_PROMPT, system=system, user=user, schema=ComposeDraft
        )
    except LLMError:
        return get_template("fallback", language)

    placeholders = _PLACEHOLDER.findall(draft.text)
    if any(key not in offered_keys for key in placeholders):
        return get_template("fallback", language)
    # Whatever is left after removing the well-formed `{key}` placeholders
    # must have no brace left either: a stray `{`/`}` (e.g. `{card_mask.upper}`,
    # `{card_mask[0]}`, `{card_mask:>99}`, `{}`) doesn't match `\w+` and so
    # escapes the check above, but str.format-style substitution on it would
    # run attribute/index access or a format spec on our own data (rejected
    # instead of ever reaching `str.format`, which we never call on the draft).
    residual = _PLACEHOLDER.sub("", draft.text)
    if "{" in residual or "}" in residual:
        return get_template("fallback", language)
    if any(char.isdigit() for char in residual):
        return get_template("fallback", language)

    values = {
        key: _format_fact(key, facts_by_key, language=language, country=country)
        for key in offered_keys
    }
    return _PLACEHOLDER.sub(lambda m: values[m.group(1)], draft.text)


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
    if key in ("expiry", "due_date"):
        return format_date(cast(date, value))
    if key == "payment_overdue":
        return format_days(cast(int, value), language)
    if key in ("credit_limit", "available_credit", "current_balance", "min_payment"):
        return _money_fact(cast(Decimal, value), facts_by_key, language=language, country=country)
    # `abstain` facts (ADR-026) arrive already localized from `nodes/abstain.py`.
    if key in (
        "card_options",
        "customer_name",
        "topic_label",
        "abstain_reason",
        "closest_action",
        "human_offer",
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
    this card's B1): `balance_due` for a credit card on `balance_due`, else
    `card_status` -- a debit card on `balance_due` gets its status described
    right after the fixed `credit_only` segment (`flows/card_info.py`). The
    "which card?" question never reaches here: it is a fixed per-action
    template the flow writes itself (`card_select.ask_which_card_text`). `facts`
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

    card_kind = facts_by_key.get("card_kind")
    is_debit = card_kind is not None and card_kind.value == "debit"
    goal: Goal = (
        "balance_due" if _current_intent(state) == "balance_due" and not is_debit else "card_status"
    )

    customer_name = state.get("customer_name")
    if customer_name:
        facts.append(Fact(key="customer_name", value=customer_name, source="customers.get_profile"))
    text = await compose_reply(
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
    return {"segments": segments}
