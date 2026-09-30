"""The `pending_reversal_explain` intent's flow node: explain a Pending or
Reversed movement (this card's B1, `02` §4.5, D3, A5).

`tx_explain` stages itself the same way `tx_search` does: no slot yet runs a
fresh search restricted to `status in [Pending, Reversed]` (`build_tx_filter`
from `tx_search`, D1); `"pick"` resumes the single pick.

D3's picking rule: one match explains it directly; two or more offers them
in the same single-pick `ui.transaction_list` `tx_search` uses
(`offer_tx_pick`); zero *with* a resolvable criterion (A1's has-criterion
flag) widens to every Pending/Reversed row of the last 12 months and offers
that instead (D5-B D2's "zero matches -> offer all" pattern); zero with none
at all (the filtered search was already that broad query) ends with the
fixed `tx_explain_none` segment. Unlike `tx_search`, this flow never asks a
clarifying question first -- the intent alone is enough to search.

`explain_tx` is this module's own pure explanation step: the cause, next
step and (for a still-open Pending hold) the clear-by date come only from
`policies/transaction_states.yaml` (A5, R8, R11) -- never an LLM guess.
`tx_search`'s own pick resume imports it (lazily, to avoid a module cycle)
for a Pending/Reversed row found inside a mixed-status search, so the two
flows never disagree on what a status means.

This module has no write tool and never imports `app.core.llm` (R6).
"""

from datetime import UTC, datetime, timedelta
from typing import Any

from langchain_core.runnables import RunnableConfig

from app.core.errors import ToolUnavailable
from app.domains.conversation.flows.tx_search import build_tx_filter, card_mask_fact, offer_tx_pick
from app.domains.conversation.graph import GraphState
from app.domains.conversation.schemas import NLUSlots
from app.domains.conversation.state import Fact
from app.domains.conversation.templates import Language, get_template
from app.domains.conversation.tools import BankReadTools
from app.domains.conversation.ui import PickerOption, QuickRepliesEvent, QuickRepliesPayload
from app.domains.localization.format import BANK_TZ, local_today
from app.domains.policy.registry import get_policies
from app.domains.policy.transaction_states import load_transaction_states_policy
from app.domains.transactions.schemas import TxFilter, TxView

__all__ = ["explain_tx", "tx_explain"]

_MERCHANT_FALLBACK: dict[Language, str] = {
    "es": "Comercio",
    "pt": "Estabelecimento",
}


async def tx_explain(state: GraphState, config: RunnableConfig) -> dict[str, Any]:
    """Resolve the criteria (restricted to Pending/Reversed), then explain,
    offer or give up (D3)."""
    pending = state.get("pending")
    node = pending["node"] if pending is not None else None

    if node == "pick":
        return await _resume_pick(state, config)
    return await _run_search(state, config)


async def _run_search(state: GraphState, config: RunnableConfig) -> dict[str, Any]:
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
        slots,
        today=today,
        tz=BANK_TZ[country],
        language=language,
        cards=cards,
        status=["Pending", "Reversed"],
    )
    try:
        rows = await bank_tools.search_transactions(tx_filter)
    except ToolUnavailable:
        return {"escalation_reason": "tool_failure"}

    if rows:
        if len(rows) == 1:
            return await explain_tx(state, config, rows[0])
        return offer_tx_pick(
            rows, cards, country, language, flow="tx_explain", prompt_kind="tx_explain_pick_ask"
        )

    if not has_criterion:
        return {"pending": None, "segments": [get_template("tx_explain_none", language)]}

    # D3: zero matches *with* a slot -> offer every Pending/Reversed row of
    # the last 12 months instead (D5-B D2's "zero matches -> offer all").
    broad_filter = TxFilter(
        date_from=today - timedelta(days=365),
        date_to=today,
        status=["Pending", "Reversed"],
        card_id=tx_filter.card_id,
    )
    try:
        rows = await bank_tools.search_transactions(broad_filter)
    except ToolUnavailable:
        return {"escalation_reason": "tool_failure"}

    if not rows:
        return {"pending": None, "segments": [get_template("tx_explain_none", language)]}
    return offer_tx_pick(
        rows, cards, country, language, flow="tx_explain", prompt_kind="tx_explain_pick_ask"
    )


async def _resume_pick(state: GraphState, config: RunnableConfig) -> dict[str, Any]:
    """The single pick itself (D3). Same re-check as `tx_search`'s own pick
    (R1, R11): exactly one offered id, then a fresh, unfiltered-but-for-
    status re-read -- Pending/Reversed rows are a naturally small set
    (A5), the same reasoning `decline_explain` applies to Declined rows."""
    language = state["language"]
    offer = state.get("tx_offer")
    selection = state.get("selection")
    if offer is None or selection is None:
        return {
            "pending": None,
            "tx_offer": None,
            "segments": [get_template("nothing_pending", language)],
        }

    offered = set(offer["offered_tx_ids"])
    if len(selection.tx_ids) != 1 or selection.tx_ids[0] not in offered:
        return {"segments": [get_template("pending_reminder", language)]}

    bank_tools: BankReadTools = config["configurable"]["bank_tools"]
    try:
        rows = await bank_tools.search_transactions(TxFilter(status=["Pending", "Reversed"]))
    except ToolUnavailable:
        return {"escalation_reason": "tool_failure"}

    tx_id = selection.tx_ids[0]
    tx = next((row for row in rows if row.tx_id == tx_id), None)
    if tx is None:
        return {
            "pending": None,
            "tx_offer": None,
            "segments": [get_template("nothing_pending", language)],
        }
    return await explain_tx(state, config, tx)


async def explain_tx(state: GraphState, config: RunnableConfig, tx: TxView) -> dict[str, Any]:
    """The Pending/Reversed explanation (D3, A5): cause, next step and (for a
    still-open Pending hold) the clear-by date all come from
    `policies/transaction_states.yaml` alone (R6, R8, R11). Writes facts for
    `compose`'s `tx_explain` goal; an overdue Pending also offers a quick
    reply to a person, reusing the `next_step` slot (`decline_explain`'s own
    self-service offer sets the precedent).
    """
    bank_tools: BankReadTools = config["configurable"]["bank_tools"]
    language = state["language"]
    country = state["country"]
    now = config["configurable"].get("now") or datetime.now(UTC)
    today = local_today(country, now)

    try:
        card_fact = await card_mask_fact(bank_tools, tx.card_id)
    except ToolUnavailable:
        return {"escalation_reason": "tool_failure"}

    policy = load_transaction_states_policy()
    # `disputes`'s own convention for a policy-sourced fact (`f"policy:
    # <stem>@{ctx.policy_version}"`): `ToolContext.policy_version` is always
    # `get_policies().hash` (`tools/registry.py`), and no flow node reads the
    # session directly -- only `load_session` does (`nodes/load_session.py`).
    source = f"policy:transaction_states@{get_policies().hash}"
    tx_source = f"bank.transactions:{tx.tx_id}"
    merchant = tx.merchant_name or _MERCHANT_FALLBACK[language]

    facts = [
        Fact(key="merchant", value=merchant, source=tx_source),
        Fact(key="amount", value=tx.amount, source=tx_source),
        Fact(key="currency", value=tx.currency, source=tx_source),
        Fact(key="tx_date", value=tx.occurred_at.date(), source=tx_source),
    ]
    if card_fact is not None:
        facts.append(card_fact)
    ui: list[Any] = []
    if tx.status == "Pending":
        clear_by = tx.occurred_at.date() + timedelta(days=policy.pending.hold_days)
        facts.append(Fact(key="tx_state_cause", value=policy.pending.cause_key, source=source))
        if clear_by < today:
            facts.append(
                Fact(
                    key="tx_state_next_step",
                    value=policy.pending.overdue_next_step_key,
                    source=source,
                )
            )
            option = PickerOption(label=get_template("tx_human_option", language))
            ui = [
                QuickRepliesEvent(
                    kind="quick_replies",
                    payload=QuickRepliesPayload(slot="next_step", options=[option]),
                )
            ]
        else:
            facts.append(
                Fact(key="tx_state_next_step", value=policy.pending.next_step_key, source=source)
            )
            facts.append(Fact(key="clear_by_date", value=clear_by, source=source))
    else:
        # D3's own status restriction: nothing but Pending/Reversed ever
        # reaches this function. A5: no twin row exists for a Reversed
        # charge, so there is only a cause and one next step.
        facts.append(Fact(key="tx_state_cause", value=policy.reversed.cause_key, source=source))
        facts.append(
            Fact(key="tx_state_next_step", value=policy.reversed.next_step_key, source=source)
        )

    update: dict[str, Any] = {"pending": None, "tx_offer": None, "facts": facts}
    if ui:
        update["ui"] = ui
    return update
