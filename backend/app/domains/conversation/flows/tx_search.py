"""The `transaction_search` intent's flow node: find a past movement by
merchant, amount and/or date (this card's B1, `02` §4.4, D1-D2, A1-A4).

`tx_search` stages itself on `pending.node`, the same shape every other
card-scoped flow uses (`decline_explain`'s own docstring): no slot yet runs
a fresh search; `"pick"` resumes the single pick, reached only through
`TurnInput.selection` (`graph._entry`, same D4-B D7 gate `decline_explain`
reuses).

D1: the search's `TxFilter` is built in code from this turn's NLU slots --
the merchant is fuzzy-matched against `KNOWN_MERCHANTS`
(`transactions.merchants.match_merchant`), the date phrase is resolved by
`localization.dates.resolve_date_expression`, and the amount is a +-10%
window -- the LLM never supplies any of the three (R6). A1: with no
resolvable criterion at all, the flow asks one fixed question and runs no
search. A2: the window never starts more than 12 months before the bank
clock's today (`config["configurable"].get("now")`, defaulting to the real
clock); with no date it *is* the last 12 months. A `card_hint` only narrows
`TxFilter.card_id` through `list_cards` -- this flow never runs the
interactive `card_select` sub-flow (D1).

One or more rows -> a single-pick `ui.transaction_list` (`multi=False`,
D1), labels formatted in code (R4), pausing at `awaiting_slot=
"transactions"` with `TxOfferState`. Zero rows -> the dates widen once by
+-3 days (still clamped, A2); zero again ends with the fixed
`tx_search_none` segment naming the filters used, formatted in code -- this
outcome is `resolved`, no pause.

Picking a row (D2): a Pending or Reversed one is explained through
`tx_explain.explain_tx` (imported lazily inside `_resume_pick` to avoid a
module cycle -- `tx_explain.py` imports `build_tx_filter`/`offer_tx_pick`
from this module at load time). Anything else (Approved, Declined, ...)
gets its details decoded from `TxView` in code (R4) as facts for `compose`'s
`tx_details` goal.

This module has no write tool and never imports `app.core.llm` (R6).
"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal
from zoneinfo import ZoneInfo

from langchain_core.runnables import RunnableConfig

from app.core.errors import AccessDenied, NotFound, ToolUnavailable
from app.domains.cards.schemas import CardSummary
from app.domains.conversation.flows.actions import fill
from app.domains.conversation.graph import GraphState
from app.domains.conversation.schemas import NLUSlots
from app.domains.conversation.state import Fact, TxOfferState, mark_segment
from app.domains.conversation.templates import Language, TemplateKind, get_template
from app.domains.conversation.tools import BankReadTools
from app.domains.conversation.ui import TransactionListEvent, TransactionListPayload, TxOption
from app.domains.localization import mask_card
from app.domains.localization.dates import resolve_date_expression
from app.domains.localization.format import BANK_TZ, Country, format_date, format_money, local_today
from app.domains.transactions.merchants import match_merchant
from app.domains.transactions.schemas import TxFilter, TxStatus, TxView

__all__ = ["build_tx_filter", "offer_tx_pick", "tx_option", "tx_search"]

_MERCHANT_FALLBACK: dict[Language, str] = {
    "es": "Comercio",
    "pt": "Estabelecimento",
}

_WINDOW_DAYS = 365
_WIDEN_DAYS = 3


async def tx_search(state: GraphState, config: RunnableConfig) -> dict[str, Any]:
    """Resolve the criteria, search, then offer or explain (D1-D2)."""
    pending = state.get("pending")
    node = pending["node"] if pending is not None else None

    if node == "pick":
        return await _resume_pick(state, config)
    return await _run_search(state, config)


async def _run_search(state: GraphState, config: RunnableConfig) -> dict[str, Any]:
    """A fresh search turn (D1): build the filter, search, widen once on a
    miss, and offer whatever is left (A1-A2)."""
    bank_tools: BankReadTools = config["configurable"]["bank_tools"]
    language = state["language"]
    country = state["country"]
    nlu = state.get("nlu")
    slots = nlu.slots if nlu is not None else NLUSlots()
    now = config["configurable"].get("now") or datetime.now(UTC)
    today = local_today(country, now)

    try:
        cards = await bank_tools.list_cards()
    except ToolUnavailable:
        return {"escalation_reason": "tool_failure"}

    tx_filter, has_criterion = build_tx_filter(
        slots, today=today, tz=BANK_TZ[country], language=language, cards=cards
    )
    if not has_criterion:
        return {
            "pending": None,
            **mark_segment("awaiting", awaiting_slot="criterion"),
            "segments": [get_template("tx_search_ask_criterion", language)],
        }

    try:
        rows = await bank_tools.search_transactions(tx_filter)
        if not rows:
            tx_filter = _widen(tx_filter, today)
            rows = await bank_tools.search_transactions(tx_filter)
    except ToolUnavailable:
        return {"escalation_reason": "tool_failure"}

    if not rows:
        text = fill(
            get_template("tx_search_none", language),
            filters=_describe_filters(tx_filter, country, language),
        )
        return {"pending": None, **mark_segment("resolved"), "segments": [text]}

    return offer_tx_pick(
        rows, cards, country, language, flow="tx_search", prompt_kind="tx_search_pick_ask"
    )


async def _resume_pick(state: GraphState, config: RunnableConfig) -> dict[str, Any]:
    """The single pick itself (D2). Re-checks the same rule `decline_explain`
    does -- exactly one id, and it must be one this flow offered (R1) --
    then re-reads that one row fresh by id rather than trust the stale offer
    (R1, R11). `TxOfferState` carries no filter to replay, and an unfiltered
    `search` returns only the newest 10 rows, so an older picked row would
    drop out of it; `get_transactions_by_ids` is own-row-only.
    """
    language = state["language"]
    offer = state.get("tx_offer")
    selection = state.get("selection")
    if offer is None or selection is None:
        return {
            "pending": None,
            "tx_offer": None,
            **mark_segment("cancelled"),
            "segments": [get_template("nothing_pending", language)],
        }

    offered = set(offer["offered_tx_ids"])
    if len(selection.tx_ids) != 1 or selection.tx_ids[0] not in offered:
        return {"segments": [get_template("pending_reminder", language)]}

    bank_tools: BankReadTools = config["configurable"]["bank_tools"]
    tx_id = selection.tx_ids[0]
    try:
        rows = await bank_tools.get_transactions_by_ids([tx_id])
    except ToolUnavailable:
        return {"escalation_reason": "tool_failure"}
    except (NotFound, AccessDenied):
        rows = []

    tx = rows[0] if rows else None
    if tx is None:
        return {
            "pending": None,
            "tx_offer": None,
            **mark_segment("cancelled"),
            "segments": [get_template("nothing_pending", language)],
        }

    if tx.status in ("Pending", "Reversed"):
        # Deferred: `tx_explain` imports `build_tx_filter`/`offer_tx_pick`
        # from this module at load time, so a top-level import here would
        # cycle (`build_graph`'s own docstring sets the same precedent).
        from app.domains.conversation.flows.tx_explain import explain_tx

        return await explain_tx(state, config, tx)
    return await _tx_details(state, config, tx)


async def card_mask_fact(bank_tools: BankReadTools, product_id: str) -> Fact | None:
    """The `card_mask` fact for a movement's product, or `None` when that
    product isn't a card (a savings/checking account movement is a valid
    Pending/Reversed row, but `get_card_details` raises `NotFound` for it).
    Callers omit the mask rather than fail the turn or invent a tail."""
    try:
        details = await bank_tools.get_card_details(product_id)
    except NotFound:
        return None
    return Fact(key="card_mask", value=details.last4, source=details.source)


async def _tx_details(state: GraphState, config: RunnableConfig, tx: TxView) -> dict[str, Any]:
    """D2: an Approved row (or any other non-Pending/Reversed status) gets
    its details decoded from `TxView`, formatted in code (R4) -- there is no
    policy to explain here, unlike a Pending/Reversed pick."""
    bank_tools: BankReadTools = config["configurable"]["bank_tools"]
    language = state["language"]

    try:
        card_fact = await card_mask_fact(bank_tools, tx.card_id)
    except ToolUnavailable:
        return {"escalation_reason": "tool_failure"}

    merchant = tx.merchant_name or _MERCHANT_FALLBACK[language]
    tx_source = f"bank.transactions:{tx.tx_id}"
    facts = [
        Fact(key="merchant", value=merchant, source=tx_source),
        Fact(key="amount", value=tx.amount, source=tx_source),
        Fact(key="currency", value=tx.currency, source=tx_source),
        Fact(key="tx_date", value=tx.occurred_at.date(), source=tx_source),
        Fact(key="channel", value=tx.channel, source=tx_source),
    ]
    if card_fact is not None:
        facts.append(card_fact)
    if tx.category is not None:
        facts.append(Fact(key="category", value=tx.category, source=tx_source))
    if tx.city is not None:
        facts.append(Fact(key="city", value=tx.city, source=tx_source))
    return {"pending": None, "tx_offer": None, "facts": facts}


def build_tx_filter(
    slots: NLUSlots,
    *,
    today: date,
    tz: ZoneInfo,
    language: Language,
    cards: list[CardSummary],
    status: list[TxStatus] | None = None,
) -> tuple[TxFilter, bool]:
    """Build a `TxFilter` from this turn's NLU slots (D1, A1-A4), and
    whether the customer actually supplied a resolvable criterion.

    `tx_search`'s ask-first gate (A1) and `tx_explain`'s "zero with a slot"
    branch (D3) both read the second value. `status` restricts the search
    (`tx_explain` passes `["Pending", "Reversed"]`); `None` means every
    status, `tx_search`'s own default.
    """
    merchant_names = match_merchant(slots.merchant_text) if slots.merchant_text else []
    window = (
        resolve_date_expression(slots.date_expression, today, tz, language)
        if slots.date_expression
        else None
    )
    has_criterion = bool(merchant_names) or slots.amount is not None or window is not None

    if window is not None:
        date_from, date_to = window
        date_from = max(date_from, today - timedelta(days=_WINDOW_DAYS))
    else:
        date_from, date_to = today - timedelta(days=_WINDOW_DAYS), today

    amount_min = amount_max = None
    if slots.amount is not None:
        amount_min = slots.amount * Decimal("0.9")
        amount_max = slots.amount * Decimal("1.1")

    tx_filter = TxFilter(
        date_from=date_from,
        date_to=date_to,
        merchant_names=merchant_names,
        amount_min=amount_min,
        amount_max=amount_max,
        currency=slots.currency,
        status=list(status) if status else [],
        card_id=_narrow_card_id(cards, slots.card_hint),
    )
    return tx_filter, has_criterion


def _narrow_card_id(cards: list[CardSummary], hint: str | None) -> str | None:
    """A2: a `card_hint` narrows the search to one card; a hint matching
    zero or more than one card (or no hint at all) leaves `card_id=None`, so
    the search covers every one of the customer's cards -- there is no
    interactive `card_select` sub-flow here (D1)."""
    if hint is None:
        return None
    if hint == "credit":
        matches = [c for c in cards if c.kind == "credit"]
    elif hint == "debit":
        matches = [c for c in cards if c.kind == "debit"]
    elif hint.startswith("last4:"):
        last4 = hint.removeprefix("last4:")
        matches = [c for c in cards if c.last4 == last4]
    else:
        matches = []
    return matches[0].card_id if len(matches) == 1 else None


def _widen(tx_filter: TxFilter, today: date) -> TxFilter:
    """Widen the window by +-3 days, re-clamped to the 12-month floor (A2).
    `date_from`/`date_to` are never `None` here -- `build_tx_filter` always
    fills a window, even with no date slot."""
    floor = today - timedelta(days=_WINDOW_DAYS)
    date_from = tx_filter.date_from or floor
    date_to = tx_filter.date_to or today
    return tx_filter.model_copy(
        update={
            "date_from": max(date_from - timedelta(days=_WIDEN_DAYS), floor),
            "date_to": date_to + timedelta(days=_WIDEN_DAYS),
        }
    )


def _describe_filters(tx_filter: TxFilter, country: Country, language: Language) -> str:
    """The filters actually used, formatted in code (R4) -- for the fixed
    `tx_search_none`/`tx_explain_none` "nothing found" replies. The amount
    window is skipped when no currency is known: money is never formatted
    without one (R4)."""
    del language  # kept for signature symmetry with the other formatters here
    parts: list[str] = []
    if tx_filter.merchant_names:
        parts.append(", ".join(tx_filter.merchant_names))
    if tx_filter.amount_min is not None and tx_filter.amount_max is not None and tx_filter.currency:
        parts.append(
            f"{format_money(tx_filter.amount_min, tx_filter.currency, country)}"
            f" - {format_money(tx_filter.amount_max, tx_filter.currency, country)}"
        )
    if tx_filter.date_from is not None and tx_filter.date_to is not None:
        if tx_filter.date_from == tx_filter.date_to:
            parts.append(format_date(tx_filter.date_from))
        else:
            parts.append(f"{format_date(tx_filter.date_from)} - {format_date(tx_filter.date_to)}")
    return ", ".join(parts)


def tx_option(
    tx: TxView, last4_by_card: dict[str, str], country: Country, language: Language
) -> TxOption:
    """`merchant · money · day-first date · •••• last4`, code-formatted
    (R4) -- `last4_by_card` is `list_cards`'s own per-card tail, since a
    search (unlike `decline_explain`'s) can span more than one card."""
    merchant = tx.merchant_name or _MERCHANT_FALLBACK[language]
    label = (
        f"{merchant} · {format_money(tx.amount, tx.currency, country)} · "
        f"{format_date(tx.occurred_at.date())}"
    )
    # A movement on a non-card product has no tail to show; never a made-up one.
    last4 = last4_by_card.get(tx.card_id)
    if last4 is not None:
        label += f" · {mask_card(last4)}"
    return TxOption(tx_id=tx.tx_id, label=label)


def offer_tx_pick(
    rows: list[TxView],
    cards: list[CardSummary],
    country: Country,
    language: Language,
    *,
    flow: Literal["tx_search", "tx_explain"],
    prompt_kind: TemplateKind,
) -> dict[str, Any]:
    """The shared single-pick offer (D1, D3): a `ui.transaction_list`
    (`multi=False`) plus a count in `prompt_kind`'s segment, pausing at
    `awaiting_slot="transactions"` with `TxOfferState`. Shared by
    `tx_search` and `tx_explain` so the two flows' pick UI never diverges.
    """
    last4_by_card = {card.card_id: card.last4 for card in cards}
    options = [tx_option(tx, last4_by_card, country, language) for tx in rows]
    prompt = fill(get_template(prompt_kind, language), count=str(len(rows)))
    offer: TxOfferState = {"flow": flow, "offered_tx_ids": [tx.tx_id for tx in rows]}
    return {
        "tx_offer": offer,
        "pending": {"flow": flow, "node": "pick", "awaiting_slot": "transactions"},
        "segments": [prompt],
        "ui": [
            TransactionListEvent(
                kind="transaction_list",
                payload=TransactionListPayload(options=options, multi=False),
            )
        ],
    }
