"""The `card_status`/`balance_due` intents' flow node (D8, D10, D13, this card's B1).

`card_info` is the graph node `route`/`_dispatch` sends both `card_status` and
`balance_due` turns to (`graph.py`'s `_INTENT_NODES`). It reads
`config["configurable"]["bank_tools"]` -- the session's own bound
`BankReadTools`, never a `customer_id` argument (R1) -- and drives
`select_card` (`flows/card_select`) over `list_cards()`'s result:

* `Selected` -- `get_card_details` for that one card, then this turn's facts
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
  "tool_failure"` only, `pending` left alone: a transient tool error
  shouldn't discard a clarification in progress. `route`/`compose` never run
  for any of these three; `fallback` (the node) picks the reply template
  (D15).

`balance_due`'s current-card resolution has one extra wrinkle (B3's queue,
`02` §3): a turn that reaches `card_info` through `next_intent` (a queued
`balance_due` riding behind, say, a just-answered `card_block`) carries no
fresh `nlu` at all -- `understand` never ran that turn (a button confirm or
an OTP resume skips it, D1/D14). There is then no `card_hint` to resolve
from, so this node reuses `state["selected_card_id"]` (set by whichever
flow -- `card_info` itself or `card_block` -- already resolved a card
earlier in the same conversation) instead of re-running `select_card` with
no hint, which would otherwise re-ask "which card?" on every multi-card
customer's queued `balance_due`. A turn with a fresh `nlu` always goes
through the normal `select_card` resolution, unaffected.
"""

from decimal import Decimal
from typing import Any, Literal

from langchain_core.runnables import RunnableConfig

from app.core.errors import NotFound, ToolUnavailable
from app.domains.cards.schemas import CardDetails
from app.domains.conversation.flows.card_select import (
    Ask,
    NoCards,
    Selected,
    ask_which_card_text,
    card_picker_event,
    load_card_select_policy,
    select_card,
)
from app.domains.conversation.graph import GraphState
from app.domains.conversation.schemas import Intent
from app.domains.conversation.state import Fact
from app.domains.conversation.tools import BankReadTools
from app.domains.localization import local_today
from app.domains.policy.escalation import load_escalation_policy
from app.domains.policy.min_payment import load_min_payment_policy, min_payment, next_due_date

__all__ = ["card_info"]

_MIN_PAYMENT_SOURCE = "policy:min_payment@v1"
_FX_SOURCE = "reference.get_fx_rate"
_PROFILE_SOURCE = "customers.get_profile"


def _current_intent(state: GraphState) -> Intent:
    """The intent this turn's `card_info` run answers (D20's queue head)."""
    queue = state.get("intent_queue") or []
    return queue[0] if queue else "card_status"


async def card_info(state: GraphState, config: RunnableConfig) -> dict[str, Any]:
    """Resolve which card, then read its status/balance facts (D8, D12, D13, B1)."""
    bank_tools: BankReadTools = config["configurable"]["bank_tools"]
    nlu = state.get("nlu")
    hint = nlu.slots.card_hint if nlu is not None else None
    failures = state.get("clarification_failures", 0)
    intent = _current_intent(state)

    # A queued `balance_due` reached with no fresh `nlu` this turn (see the
    # module docstring): reuse the card an earlier flow node already
    # resolved this conversation instead of re-asking with no hint.
    reused_card_id = state.get("selected_card_id") if nlu is None else None

    if reused_card_id is not None:
        card_id = reused_card_id
    else:
        try:
            cards = await bank_tools.list_cards()
        except ToolUnavailable:
            return {"escalation_reason": "tool_failure"}

        policy = load_card_select_policy()
        outcome = select_card(cards, hint, failures, policy, state["language"])

        if isinstance(outcome, Ask):
            return {
                "pending": {
                    "flow": "card_info",
                    "node": "card_select",
                    "awaiting_slot": "card_hint",
                },
                "clarification_failures": outcome.failures,
                "segments": [
                    ask_which_card_text(
                        "balance" if intent == "balance_due" else "status",
                        outcome,
                        state["language"],
                    )
                ],
                "ui": [card_picker_event(outcome)],
            }
        if isinstance(outcome, NoCards):
            return {"escalation_reason": "no_cards", "pending": None, "clarification_failures": 0}
        if not isinstance(outcome, Selected):
            # The remaining outcome is `Fallback`: clarification exhausted
            # (D12, D15). Clear `pending`/`clarification_failures` too, or the
            # next turn starts already at the limit and falls back forever
            # regardless of its hint (orchestrator repair round 1).
            # `tool_failure` above is left alone: a transient tool error
            # shouldn't discard a clarification in progress.
            return {
                "escalation_reason": "clarification_exhausted",
                "pending": None,
                "clarification_failures": 0,
            }
        card_id = outcome.card_id

    try:
        details = await bank_tools.get_card_details(card_id)
    except ToolUnavailable:
        return {"escalation_reason": "tool_failure"}

    facts = await _facts(intent, details, bank_tools, state)
    return {
        "selected_card_id": card_id,
        "pending": None,
        "clarification_failures": 0,
        "facts": facts,
    }


async def _facts(
    intent: Intent, details: CardDetails, bank_tools: BankReadTools, state: GraphState
) -> list[Fact]:
    """This turn's facts; the reply itself always goes through `compose`
    (R4, R6). ADR-034 retired the fixed `credit_only` text a debit card got
    on `balance_due`.
    """
    if intent == "balance_due" and details.kind == "credit":
        facts = await _credit_balance_facts(details, bank_tools, country=state["country"])
    elif intent == "balance_due":
        facts = await _debit_balance_facts(details, bank_tools, country=state["country"])
    else:
        facts = _card_status_facts(details)

    read_only = await _read_only_note_fact(bank_tools)
    if read_only is not None:
        facts = [*facts, read_only]
    return facts


def _card_status_facts(details: CardDetails) -> list[Fact]:
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


async def _debit_balance_facts(
    details: CardDetails, bank_tools: BankReadTools, *, country: Literal["MX", "CO", "AR"]
) -> list[Fact]:
    """`balance_due` on a debit card (ADR-034): mask, kind, status and its
    available balance (`current_balance`, as `available_balance`), plus the
    hidden `currency` (and MXN-estimate facts) that format it. Due date and
    minimum payment are credit-only.
    """
    candidates: list[tuple[str, Any]] = [
        ("card_mask", details.last4),
        ("card_kind", details.kind),
        ("status", details.status),
        ("available_balance", details.current_balance),
        ("currency", details.currency),
    ]
    facts = [
        Fact(key=key, value=value, source=details.source)
        for key, value in candidates
        if value is not None
    ]
    return [*facts, *await _fx_facts(details, bank_tools, country=country)]


async def _credit_balance_facts(
    details: CardDetails, bank_tools: BankReadTools, *, country: Literal["MX", "CO", "AR"]
) -> list[Fact]:
    """`balance_due` on a credit card (D5, D18, this card's B1).

    The minimum payment and due date are synthetic policy, not a bank
    figure (D5, `synthetic_footnote`), so they carry `_MIN_PAYMENT_SOURCE`
    rather than `details.source`. `payment_overdue` is a separate fact --
    there is no overdue term in the formula itself. The MXN estimate (D18)
    only applies to an MX card billed in USD; `NotFound` on the FX pair
    means no estimate this turn, not an error (D3).
    """
    policy = load_min_payment_policy()
    balance = details.current_balance if details.current_balance is not None else Decimal("0")
    due_date = next_due_date(local_today(country), policy)
    min_pay = min_payment(balance, details.currency, policy)

    candidates: list[tuple[str, Any, str]] = [
        ("current_balance", details.current_balance, details.source),
        ("due_date", due_date, _MIN_PAYMENT_SOURCE),
        ("min_payment", min_pay, _MIN_PAYMENT_SOURCE),
        ("available_credit", details.available_credit, details.source),
        ("currency", details.currency, details.source),
    ]
    facts = [
        Fact(key=key, value=value, source=source)
        for key, value, source in candidates
        if value is not None
    ]

    if details.days_past_due is not None and details.days_past_due > 0:
        facts.append(
            Fact(key="payment_overdue", value=details.days_past_due, source=details.source)
        )

    return [*facts, *await _fx_facts(details, bank_tools, country=country)]


async def _fx_facts(
    details: CardDetails, bank_tools: BankReadTools, *, country: Literal["MX", "CO", "AR"]
) -> list[Fact]:
    """The MXN estimate's facts (D18): only for an MX card billed in USD.
    `NotFound` on the FX pair means no estimate this turn, not an error (D3).
    """
    if country != "MX" or details.currency != "USD":
        return []
    try:
        fx = await bank_tools.get_fx_rate("USD", "MXN")
    except NotFound:
        return []
    return [
        Fact(key="fx_rate", value=fx.rate, source=_FX_SOURCE),
        Fact(key="fx_as_of", value=fx.as_of, source=_FX_SOURCE),
    ]


async def _read_only_note_fact(bank_tools: BankReadTools) -> Fact | None:
    """D10/ADR-021: a customer who isn't Active gets a `read_only_note` fact
    naming their status, on either `card_status` or `balance_due`.
    """
    profile = await bank_tools.get_profile()
    policy = load_escalation_policy()
    if profile.customer_status in policy.customer_not_active.statuses:
        return Fact(key="read_only_note", value=profile.customer_status, source=_PROFILE_SOURCE)
    return None
