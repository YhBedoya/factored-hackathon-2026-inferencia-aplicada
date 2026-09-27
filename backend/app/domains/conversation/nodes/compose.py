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
`state["pending"]` and passes `state["facts"]` -- this turn's only, thanks
to `load_session`'s per-turn reset (Q3) -- through to `compose_reply`.
"""

import re
from datetime import date
from decimal import Decimal
from typing import Literal, cast

from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, ConfigDict

from app.core.llm import LLMClient, LLMError, PromptRef
from app.domains.conversation.graph import GraphState, TurnOutput
from app.domains.conversation.prompts import load_prompt
from app.domains.conversation.state import Fact
from app.domains.conversation.templates import Language, get_template
from app.domains.localization import format_date, format_money, kind_label, mask_card, status_label

__all__ = ["ComposeDraft", "compose", "compose_reply"]

_PROMPT = PromptRef("compose", 2)
_PLACEHOLDER = re.compile(r"\{(\w+)\}")

Goal = Literal["card_status", "ask_which_card"]
Country = Literal["MX", "CO", "AR"]


class ComposeDraft(BaseModel):
    """The compose call's structured output (D10, §"Contracts")."""

    model_config = ConfigDict(extra="forbid")

    text: str


async def compose_reply(
    llm: LLMClient, *, language: Language, country: Country, goal: Goal, facts: list[Fact]
) -> str:
    """Write one short reply from `facts` for `goal`, in `language` (D10).

    Only fact keys (never values) reach the LLM. `currency` is never offered
    as a placeholder -- it is only used in code to format `credit_limit`/
    `available_credit`.
    """
    facts_by_key = {fact.key: fact for fact in facts}
    offered_keys = [key for key in facts_by_key if key != "currency"]

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
    if key == "expiry":
        return format_date(cast(date, value))
    if key in ("credit_limit", "available_credit"):
        currency_fact = facts_by_key.get("currency")
        currency = str(currency_fact.value) if currency_fact is not None else ""
        return format_money(cast(Decimal, value), currency, country)
    if key == "card_options":
        return str(value)
    raise ValueError(f"compose: no formatter for fact key {key!r}")


async def compose(state: GraphState, config: RunnableConfig) -> TurnOutput:
    """Graph wrapper around `compose_reply`: picks the goal, then fills the reply.

    The goal is `ask_which_card` while a flow is waiting on the `card_hint`
    slot (`state["pending"]`), else `card_status` (D8, D12). `facts` are read
    straight off `state` -- the per-turn reset in `load_session` (Q3) is what
    makes that safe to pass through unfiltered.
    """
    llm: LLMClient = config["configurable"]["llm"]
    pending = state.get("pending")
    awaits_card_hint = pending is not None and pending["awaiting_slot"] == "card_hint"
    goal: Goal = "ask_which_card" if awaits_card_hint else "card_status"
    text = await compose_reply(
        llm,
        language=state["language"],
        country=state["country"],
        goal=goal,
        facts=state.get("facts", []),
    )
    return {"reply": text}
