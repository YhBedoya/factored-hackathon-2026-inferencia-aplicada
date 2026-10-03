"""The `decline_explain` intent's flow node: explain a declined purchase
(this card's B1, `02` §4.3).

`decline_explain` stages itself on `pending.node`, the same shape every
other card-scoped flow uses (`unrecognized_charge`'s own docstring, D4-B):
no slot yet (or `"card_select"`) runs the shared `card_select` sub-flow
first; `"pick"` resumes the single pick, reached only through
`TurnInput.selection` (`graph._entry`, D2 -- `understand` never runs on
this turn, and the pick is never saved as a customer message).

D2 picks which decline to explain: with no `merchant_text`/`amount` slot,
the newest decline (`transactions.search`'s own newest-first order, D1);
otherwise a case-insensitive merchant match or amount +-10% narrows the
<=10 declines. One match explains it directly; two or more offers those in
a single-pick `ui.transaction_list`; zero offers every decline instead. The
`date_expression` slot is ignored until the `tx_search` date resolver ships
(G14, D7-B).

`explain_decline` maps the code through `policies/decline_codes.yaml`
(D4): a `DeclineCodeUnknown` or an empty card (`decline_none`) answers with
a fixed template and makes no LLM call (D5). Otherwise this flow writes the
turn's facts -- merchant, amount, date and card mask formatted in code
(R4), plus `decline_cause`/`decline_next_step` carrying only the policy's
key, never the LLM's own wording of what the code means (D6, R8) -- and
lets `graph._after_flow` route to `compose`. `self_service` (code 54) adds
a `ui.quick_replies` offering the replacement flow by name (D7, ADR-026):
tapping it sends the label as text, so NLU routes it as
`replacement_request` on its own turn -- this flow never starts a plan.

This module has no write tool and never imports `app.core.llm` (R6).
"""

from decimal import Decimal
from typing import Any

from langchain_core.runnables import RunnableConfig

from app.core.errors import DeclineCodeUnknown, ToolUnavailable
from app.domains.cards.schemas import CardDetails
from app.domains.conversation.flows.actions import fill
from app.domains.conversation.flows.card_select import (
    Ask,
    Fallback,
    NoCards,
    card_picker_event,
    load_card_select_policy,
    select_card,
)
from app.domains.conversation.graph import GraphState
from app.domains.conversation.state import DeclineState, Fact, mark_segment
from app.domains.conversation.templates import Language, get_template
from app.domains.conversation.tools import BankReadTools
from app.domains.conversation.ui import (
    PickerOption,
    QuickRepliesEvent,
    QuickRepliesPayload,
    TransactionListEvent,
    TransactionListPayload,
    TxOption,
)
from app.domains.localization import mask_card
from app.domains.localization.format import Country, format_date, format_money
from app.domains.transactions.schemas import TxFilter, TxView

__all__ = ["decline_explain"]

_MERCHANT_FALLBACK: dict[Language, str] = {
    "es": "Comercio",
    "pt": "Estabelecimento",
}


async def decline_explain(state: GraphState, config: RunnableConfig) -> dict[str, Any]:
    """Resolve which card, then which decline, then explain it (D1-D7)."""
    pending = state.get("pending")
    node = pending["node"] if pending is not None else None

    if node == "pick":
        return await _resume_pick(state, config)
    return await _select_card(state, config)


async def _select_card(state: GraphState, config: RunnableConfig) -> dict[str, Any]:
    """Fresh turn, or a `card_hint` resume: the same `card_select` sub-flow
    every card-scoped intent runs first, then the decline lookup below."""
    bank_tools: BankReadTools = config["configurable"]["bank_tools"]
    language = state["language"]
    nlu = state.get("nlu")
    hint = nlu.slots.card_hint if nlu is not None else None
    failures = state.get("clarification_failures", 0)

    try:
        cards = await bank_tools.list_cards()
    except ToolUnavailable:
        return {"escalation_reason": "tool_failure"}

    policy = load_card_select_policy()
    outcome = select_card(cards, hint, failures, policy, language)

    if isinstance(outcome, Ask):
        text = get_template("ask_which_card_decline", language).replace(
            "{card_options}", outcome.card_options
        )
        return {
            "pending": {
                "flow": "decline_explain",
                "node": "card_select",
                "awaiting_slot": "card_hint",
            },
            "clarification_failures": outcome.failures,
            "segments": [text],
            "ui": [card_picker_event(outcome)],
        }
    if isinstance(outcome, NoCards):
        return {"escalation_reason": "no_cards", "pending": None, "clarification_failures": 0}
    if isinstance(outcome, Fallback):
        return {
            "escalation_reason": "clarification_exhausted",
            "pending": None,
            "clarification_failures": 0,
        }

    update: dict[str, Any] = {"selected_card_id": outcome.card_id, "clarification_failures": 0}
    update.update(await _resolve_declines(state, config, outcome.card_id))
    return update


async def _resolve_declines(
    state: GraphState, config: RunnableConfig, card_id: str
) -> dict[str, Any]:
    """`transactions.search` over this card's Declined rows (D1), then D2's
    picking rule: explain directly, offer a narrowed set, or offer all."""
    bank_tools: BankReadTools = config["configurable"]["bank_tools"]
    language = state["language"]
    country = state["country"]

    try:
        details = await bank_tools.get_card_details(card_id)
        declines = await bank_tools.search_transactions(
            TxFilter(card_id=card_id, status=["Declined"])
        )
    except ToolUnavailable:
        return {"escalation_reason": "tool_failure"}

    if not declines:
        return {
            "pending": None,
            "decline": None,
            **mark_segment("resolved"),
            "segments": [get_template("decline_none", language)],
        }

    nlu = state.get("nlu")
    slots = nlu.slots if nlu is not None else None
    merchant = slots.merchant_text if slots is not None else None
    amount = slots.amount if slots is not None else None

    if merchant is None and amount is None:
        # D2: no slot at all -- `search_transactions` already returns newest
        # first, so the head of the list is the most recent decline.
        return await _explain(state, config, details, declines[0])

    matches = _filter_declines(declines, merchant, amount)
    if len(matches) == 1:
        return await _explain(state, config, details, matches[0])
    candidates = matches if matches else declines
    return _offer(details, candidates, country, language)


def _filter_declines(
    declines: list[TxView], merchant: str | None, amount: Decimal | None
) -> list[TxView]:
    """D2: a transaction counts if it matches whichever of `merchant_text`
    (case-insensitive, exact on `merchant_name`) or `amount` (+-10%) this
    turn's NLU actually filled. The date slot is never read here."""
    matches: list[TxView] = []
    for tx in declines:
        if (
            merchant is not None
            and tx.merchant_name is not None
            and tx.merchant_name.casefold() == merchant.casefold()
        ):
            matches.append(tx)
            continue
        if amount is not None:
            lower, upper = amount * Decimal("0.9"), amount * Decimal("1.1")
            if lower <= tx.amount <= upper:
                matches.append(tx)
    return matches


def _offer(
    details: CardDetails, candidates: list[TxView], country: Country, language: Language
) -> dict[str, Any]:
    """D2's offer branch: a single-pick `ui.transaction_list` (`multi=False`,
    D3), pausing on `awaiting_slot="transactions"` same as
    `unrecognized_charge`'s pick, but this flow's own `decline` state and
    `"pick"` node so the two never share a checkpoint slot."""
    options = [_tx_option(tx, details.last4, country, language) for tx in candidates]
    prompt = fill(get_template("decline_pick_ask", language), card_last4=details.last4)
    decline: DeclineState = {
        "card_id": details.card_id,
        "offered_tx_ids": [tx.tx_id for tx in candidates],
    }
    return {
        "decline": decline,
        "pending": {"flow": "decline_explain", "node": "pick", "awaiting_slot": "transactions"},
        "segments": [prompt],
        "ui": [
            TransactionListEvent(
                kind="transaction_list",
                payload=TransactionListPayload(options=options, multi=False),
            )
        ],
    }


def _tx_option(tx: TxView, last4: str, country: Country, language: Language) -> TxOption:
    """`merchant · money · day-first date · •••• last4`, code-formatted (R4)."""
    merchant = tx.merchant_name or _MERCHANT_FALLBACK[language]
    label = (
        f"{merchant} · {format_money(tx.amount, tx.currency, country)} · "
        f"{format_date(tx.occurred_at.date())} · {mask_card(last4)}"
    )
    return TxOption(tx_id=tx.tx_id, label=label)


async def _resume_pick(state: GraphState, config: RunnableConfig) -> dict[str, Any]:
    """The single pick itself (D3). The route's own D7-style gate (T7) checks
    `selection.tx_ids` against `decline.offered_tx_ids` before this turn even
    runs; this re-checks the same rule -- exactly one id, and it must be one
    this flow offered -- so the flow never trusts an id it didn't offer,
    whatever entry point reached it (R1)."""
    language = state["language"]
    decline = state.get("decline")
    selection = state.get("selection")
    if decline is None or selection is None:
        return {
            "pending": None,
            **mark_segment("cancelled"),
            "segments": [get_template("nothing_pending", language)],
        }

    offered = set(decline["offered_tx_ids"])
    if len(selection.tx_ids) != 1 or selection.tx_ids[0] not in offered:
        return {"segments": [get_template("pending_reminder", language)]}

    bank_tools: BankReadTools = config["configurable"]["bank_tools"]
    try:
        details = await bank_tools.get_card_details(decline["card_id"])
        declines = await bank_tools.search_transactions(
            TxFilter(card_id=decline["card_id"], status=["Declined"])
        )
    except ToolUnavailable:
        return {"escalation_reason": "tool_failure"}

    tx_id = selection.tx_ids[0]
    tx = next((row for row in declines if row.tx_id == tx_id), None)
    if tx is None:
        # The offered transaction no longer shows up as Declined: never
        # trust the stale offer over a fresh read (R1, R11).
        return {
            "pending": None,
            "decline": None,
            **mark_segment("cancelled"),
            "segments": [get_template("nothing_pending", language)],
        }
    return await _explain(state, config, details, tx)


async def _explain(
    state: GraphState, config: RunnableConfig, details: CardDetails, tx: TxView
) -> dict[str, Any]:
    """D4, D6: `transactions.explain_decline` -> this turn's facts, code-
    formatted values behind LLM-safe placeholder keys (R4, R6). `decline_cause`
    and `decline_next_step` carry only the policy's own key -- `compose`
    renders each one through its fixed ES/PT template, so the LLM never picks
    what a decline code means (D6, R8). D7's replacement offer rides the same
    turn as the explanation, not a separate one."""
    bank_tools: BankReadTools = config["configurable"]["bank_tools"]
    language = state["language"]

    try:
        explanation = await bank_tools.explain_decline(tx.tx_id)
    except DeclineCodeUnknown:
        return {
            "pending": None,
            "decline": None,
            **mark_segment("resolved"),
            "segments": [get_template("decline_unknown", language)],
        }
    except ToolUnavailable:
        return {"escalation_reason": "tool_failure"}

    source = f"bank.transactions:{tx.tx_id}"
    merchant = tx.merchant_name or _MERCHANT_FALLBACK[language]
    facts = [
        Fact(key="merchant", value=merchant, source=source),
        Fact(key="amount", value=tx.amount, source=source),
        Fact(key="currency", value=tx.currency, source=source),
        Fact(key="tx_date", value=tx.occurred_at.date(), source=source),
        Fact(key="card_mask", value=details.last4, source=details.source),
        Fact(key="decline_cause", value=explanation.cause_key, source=explanation.source),
        Fact(key="decline_next_step", value=explanation.next_step_key, source=explanation.source),
    ]
    update: dict[str, Any] = {"pending": None, "decline": None, "facts": facts}
    if explanation.self_service:
        option = PickerOption(label=get_template("decline_replacement_option", language))
        update["ui"] = [
            QuickRepliesEvent(
                kind="quick_replies",
                payload=QuickRepliesPayload(slot="next_step", options=[option]),
            )
        ]
    return update
