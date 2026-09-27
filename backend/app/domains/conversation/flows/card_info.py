"""The `card_status` intent's flow node: select a card, then read its facts (D8, D13).

`card_info` is the graph node `route` sends `card_status` turns (fresh or a
pending `card_hint` clarification) to. It reads `config["configurable"]
["bank_tools"]` -- the session's own bound `BankReadTools`, never a
`customer_id` argument (R1) -- and drives `select_card` (`flows/card_select`)
over `list_cards()`'s result:

* `Selected` -- `get_card_details` for that one card, then D13's facts
  (values only; `compose`/`app.domains.localization` do all the formatting,
  R4). Clears `pending` and resets `clarification_failures` (a finished
  clarification shouldn't count against the next one; D12 says nothing to
  the contrary).
* `Ask` -- re-asks with `pending.awaiting_slot = "card_hint"` and a single
  `card_options` fact, the masked-options string `select_card` already built
  in code (R4).
* `NoCards` -- no hint, no eligible card at all: `escalation_reason =
  "no_cards"`, no facts (human decision, T6/T8/T10 state-file entries).
* `Fallback` (clarification exhausted) -- `escalation_reason =
  "clarification_exhausted"`, no facts. Same as `NoCards`, this also clears
  `pending`/`clarification_failures` so the next turn doesn't start already
  at the limit (orchestrator repair round 1).
* A `ToolUnavailable` from either tool call -- `escalation_reason =
  "tool_unavailable"` only, `pending` left alone: a transient tool error
  shouldn't discard a clarification in progress. `route`/`compose` never run
  for any of these three; `fallback` (the node) picks the reply template
  (D15).
"""

from typing import Any

from langchain_core.runnables import RunnableConfig

from app.core.errors import ToolUnavailable
from app.domains.cards.schemas import CardDetails
from app.domains.conversation.flows.card_select import (
    Ask,
    NoCards,
    Selected,
    load_card_select_policy,
    select_card,
)
from app.domains.conversation.graph import GraphState
from app.domains.conversation.state import Fact
from app.domains.conversation.tools import BankReadTools

__all__ = ["card_info"]

_CARD_OPTIONS_SOURCE = "conversation.card_select"


async def card_info(state: GraphState, config: RunnableConfig) -> dict[str, Any]:
    """Resolve which card, then read its status facts (D8, D12, D13)."""
    bank_tools: BankReadTools = config["configurable"]["bank_tools"]
    nlu = state.get("nlu")
    hint = nlu.slots.card_hint if nlu is not None else None
    failures = state.get("clarification_failures", 0)

    try:
        cards = await bank_tools.list_cards()
    except ToolUnavailable:
        return {"escalation_reason": "tool_unavailable"}

    policy = load_card_select_policy()
    outcome = select_card(cards, hint, failures, policy, state["language"])

    if isinstance(outcome, Selected):
        try:
            details = await bank_tools.get_card_details(outcome.card_id)
        except ToolUnavailable:
            return {"escalation_reason": "tool_unavailable"}
        return {
            "selected_card_id": outcome.card_id,
            "pending": None,
            "clarification_failures": 0,
            "facts": _card_facts(details),
        }

    if isinstance(outcome, Ask):
        return {
            "pending": {"flow": "card_info", "node": "card_select", "awaiting_slot": "card_hint"},
            "clarification_failures": outcome.failures,
            "facts": [
                Fact(key="card_options", value=outcome.card_options, source=_CARD_OPTIONS_SOURCE)
            ],
        }

    if isinstance(outcome, NoCards):
        return {"escalation_reason": "no_cards", "pending": None, "clarification_failures": 0}

    # The remaining outcome is `Fallback`: clarification exhausted (D12, D15).
    # Clear `pending`/`clarification_failures` too, or the next turn starts
    # already at the limit and falls back forever regardless of its hint
    # (orchestrator repair round 1). `tool_unavailable` above is left alone:
    # a transient tool error shouldn't discard a clarification in progress.
    return {
        "escalation_reason": "clarification_exhausted",
        "pending": None,
        "clarification_failures": 0,
    }


def _card_facts(details: CardDetails) -> list[Fact]:
    """D13's facts for one card: mask, kind, status, expiry, plus credit-only
    money facts (limit, available credit, currency) when `details.kind ==
    "credit"`. Every fact's `source` is `CardDetails.source` (`04` §1). Raw
    data can carry a `None` `expiration_date` or a null money field; a fact
    with a `None` value is skipped rather than emitted, since `compose`
    would otherwise call a formatter on `None` and crash (orchestrator
    repair round 1).
    """
    candidates: list[tuple[str, Any]] = [
        ("card_mask", details.last4),
        ("card_kind", details.kind),
        ("status", details.status),
        ("expiry", details.expiration_date),
    ]
    if details.kind == "credit":
        candidates.extend(
            [
                ("credit_limit", details.credit_limit),
                ("available_credit", details.available_credit),
                ("currency", details.currency),
            ]
        )
    return [
        Fact(key=key, value=value, source=details.source)
        for key, value in candidates
        if value is not None
    ]
