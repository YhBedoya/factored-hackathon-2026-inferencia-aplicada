"""The agent's read tools (D18, D20, D21, D22): thin code wrappers over the session's
`bank_tools` that return the facts the pipeline flows build today.

Every tool reads through `config["configurable"]["bank_tools"]` (so the audit rows keep
their current names), builds its facts with the flows' own builders, registers them on
the turn's `TurnRefs` and returns the fenced `{reference, value}` text (R4, R6). A card
or transaction argument is a handle from this turn (`c1`, `t1`); an unknown handle is
never looked up (R1). A search with no card keeps only the rows on the customer's cards:
`transactions.search` also returns loan and account rows, which no card tool can explain.
No tool takes a `customer_id`, computes a sum or compares, and this module holds no write
tool: `ToolUnavailable` and `AccessDenied` propagate to the node.
"""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast

from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field

from app.core.errors import NotFound
from app.core.llm import LoopTool
from app.domains.cards.schemas import CardDetails
from app.domains.conversation.agent.refs import TurnRefs
from app.domains.conversation.flows.card_info import (
    _card_status_facts,
    _credit_balance_facts,
    _debit_balance_facts,
)
from app.domains.conversation.flows.decline_explain import _explain, _filter_declines
from app.domains.conversation.flows.tx_explain import explain_tx
from app.domains.conversation.flows.tx_search import (
    _tx_details,
    _widen,
    build_tx_filter,
    tx_option,
)
from app.domains.conversation.flows.unrecognized_charge import _tx_option as _dispute_tx_option
from app.domains.conversation.graph import GraphState
from app.domains.conversation.nodes.abstain import (
    _HUMAN_OFFERS,
    _REASONS,
    _TOPIC_LABELS,
    _closest_action,
)
from app.domains.conversation.nodes.abstain import (
    _SOURCE as _SCOPE_SOURCE,
)
from app.domains.conversation.schemas import NLUSlots
from app.domains.conversation.state import DisputeState, Fact
from app.domains.conversation.templates import Language
from app.domains.conversation.tools import BankReadTools
from app.domains.conversation.ui import TransactionListEvent, TransactionListPayload
from app.domains.localization.format import BANK_TZ, local_today
from app.domains.policy.disputes import load_disputes_policy
from app.domains.policy.registry import get_policies
from app.domains.transactions.schemas import TxFilter, TxStatus, TxView

__all__ = ["read_tools", "register_tx_rows"]

_UNKNOWN_REF = "unknown reference: use a card or transaction reference from this turn's results."
_NO_CARD_REF = "unknown reference: call card_status first to get the card references."
_MERCHANT_FALLBACK = {"es": "Comercio", "pt": "Estabelecimento"}


async def register_tx_rows(
    rows: list[TxView], refs: TurnRefs, bank_tools: BankReadTools, language: Language
) -> list[str]:
    """Register each row as a `t` reference with the facts of a transaction list; return the
    handles in row order. `fraud_score` is never a fact (it is not the agent's to word)."""
    cards = await bank_tools.list_cards()
    last4_by_card = {card.card_id: card.last4 for card in cards}
    handles: list[str] = []
    for tx in rows:
        source = f"bank.transactions:{tx.tx_id}"
        facts = [
            Fact(
                key="merchant",
                value=tx.merchant_name or _MERCHANT_FALLBACK[language],
                source=source,
            ),
            Fact(key="amount", value=tx.amount, source=source),
            Fact(key="currency", value=tx.currency, source=source),
            Fact(key="tx_date", value=tx.occurred_at.date(), source=source),
        ]
        last4 = last4_by_card.get(tx.card_id)
        if last4 is not None:
            facts.append(Fact(key="card_mask", value=last4, source=source))
        handles.append(refs.add_tx(tx.tx_id, facts))
    return handles


class _CardStatusArgs(BaseModel):
    card: str | None = Field(default=None, description="Card reference (c1); omit for every card.")


class _CardArgs(BaseModel):
    card: str = Field(description="Card reference from card_status (c1).")


class _SearchArgs(BaseModel):
    merchant_text: str | None = None
    date_expression: str | None = Field(default=None, description="e.g. 'last week', 'ayer'.")
    amount: Decimal | None = None
    currency: str | None = Field(default=None, pattern=r"^(COP|ARS|USD|MXN)$")
    card: str | None = Field(default=None, description="Card reference (c1) to narrow to.")
    status: list[TxStatus] = Field(default_factory=list)


class _DeclineArgs(BaseModel):
    transaction: str | None = Field(default=None, description="Transaction reference (t1).")
    card: str | None = Field(default=None, description="Card reference (c1) to narrow to.")
    merchant_text: str | None = None
    amount: Decimal | None = None


class _ScopeArgs(BaseModel):
    topic: str = Field(description="A scope topic key.")


def read_tools(state: GraphState, config: RunnableConfig, refs: TurnRefs) -> list[LoopTool]:
    """The turn's read tools, closed over the session's `bank_tools` and `refs`."""
    bank_tools: BankReadTools = config["configurable"]["bank_tools"]
    language = state["language"]
    country = state.get("country") or refs._country
    # The flows' builders read `state["country"]`; hand them a complete one.
    flow_state = cast(GraphState, {**state, "country": country})

    async def _card_facts(details: CardDetails) -> str:
        facts = _card_status_facts(details)
        if details.locked and details.status == "Active":
            # A temporary lock is not a product status (same override as `card_info`).
            facts = [
                Fact(key=f.key, value="Locked", source=f.source) if f.key == "status" else f
                for f in facts
            ]
        return refs.render(refs.add_card(details.card_id, facts))

    async def card_status(args: BaseModel) -> str:
        card = cast(_CardStatusArgs, args).card
        if card is not None:
            card_id = refs.card_id(card)
            if card_id is None:
                return _NO_CARD_REF
            return await _card_facts(await bank_tools.get_card_details(card_id))
        parts = [
            await _card_facts(await bank_tools.get_card_details(summary.card_id))
            for summary in await bank_tools.list_cards()
        ]
        return "\n".join(parts) if parts else "no cards"

    async def balance_due(args: BaseModel) -> str:
        card_id = refs.card_id(cast(_CardArgs, args).card)
        if card_id is None:
            return _NO_CARD_REF
        details = await bank_tools.get_card_details(card_id)
        if details.kind != "credit":
            return "not a credit card: use debit_balance for this card."
        facts = await _credit_balance_facts(details, bank_tools, country=country)
        return refs.render(refs.add_card(card_id, facts))

    async def debit_balance(args: BaseModel) -> str:
        card_id = refs.card_id(cast(_CardArgs, args).card)
        if card_id is None:
            return _NO_CARD_REF
        details = await bank_tools.get_card_details(card_id)
        if details.kind != "debit":
            return "not a debit card: use balance_due for this card."
        facts = await _debit_balance_facts(details, bank_tools, country=country)
        return refs.render(refs.add_card(card_id, facts))

    async def _card_rows(rows: list[TxView]) -> list[TxView]:
        """The rows on the customer's cards; a search with no card returns every product's."""
        card_ids = {card.card_id for card in await bank_tools.list_cards()}
        return [tx for tx in rows if tx.card_id in card_ids]

    async def _list_rows(rows: list[TxView]) -> str:
        """Register each row as a transaction reference; offer the pick when several (D21)."""
        handles = await register_tx_rows(rows, refs, bank_tools, language)
        if len(rows) > 1:
            last4_by_card = {card.card_id: card.last4 for card in await bank_tools.list_cards()}
            # Built here, not through `offer_tx_pick`: that one is typed for the pipeline
            # flows and adds a template segment the agent words itself.
            options = [tx_option(tx, last4_by_card, country, language) for tx in rows]
            refs.graph_update.update(
                {
                    "ui": [
                        TransactionListEvent(
                            kind="transaction_list",
                            payload=TransactionListPayload(options=options, multi=False),
                        )
                    ],
                    "tx_offer": {"flow": "agent", "offered_tx_ids": [tx.tx_id for tx in rows]},
                    "pending": {"flow": "agent", "node": "pick", "awaiting_slot": "transactions"},
                }
            )
        return "\n".join(refs.render(handle) for handle in handles)

    async def search_transactions(args: BaseModel) -> str:
        a = cast(_SearchArgs, args)
        card_id: str | None = None
        if a.card is not None:
            card_id = refs.card_id(a.card)
            if card_id is None:
                return _NO_CARD_REF
        now = config["configurable"].get("now") or datetime.now(UTC)
        today = local_today(country, now)
        slots = NLUSlots(
            merchant_text=a.merchant_text,
            date_expression=a.date_expression,
            amount=a.amount,
            currency=cast(Any, a.currency),
        )
        tx_filter, has_criterion = build_tx_filter(
            slots,
            today=today,
            tz=BANK_TZ[country],
            language=language,
            cards=await bank_tools.list_cards(),
            status=a.status or None,
        )
        if not (has_criterion or card_id or a.status):
            return "no search criterion: ask the customer for a merchant, an amount or a date."
        if card_id is not None:
            tx_filter = tx_filter.model_copy(update={"card_id": card_id})
        rows = await _card_rows(await bank_tools.search_transactions(tx_filter))
        if not rows:
            rows = await _card_rows(await bank_tools.search_transactions(_widen(tx_filter, today)))
        if not rows:
            return "no matching transactions."
        return await _list_rows(rows)

    async def dispute_candidates(args: BaseModel) -> str:
        card_id = refs.card_id(cast(_CardArgs, args).card)
        if card_id is None:
            return _NO_CARD_REF
        # The flow's own search: the statuses come from `disputes.yaml`, none is written here.
        policy = load_disputes_policy()
        details = await bank_tools.get_card_details(card_id)
        rows = await bank_tools.search_transactions(
            TxFilter(card_id=card_id, status=cast(list[TxStatus], policy.candidate_statuses))
        )
        if not rows:
            return "no candidate transactions."
        handles = await register_tx_rows(rows, refs, bank_tools, language)
        options = [_dispute_tx_option(tx, details.last4, country, language) for tx in rows]
        dispute: DisputeState = {
            "card_id": card_id,
            "offered_tx_ids": [tx.tx_id for tx in rows],
            "fraud_scores": {tx.tx_id: tx.fraud_score for tx in rows},
            "picked_tx_ids": [],
            "answers": [],
            "question_index": 0,
            "compromise": False,
            "block_refused": False,
        }
        refs.graph_update.update(
            {
                "ui": [
                    TransactionListEvent(
                        kind="transaction_list",
                        payload=TransactionListPayload(options=options, multi=True),
                    )
                ],
                "dispute": dispute,
                "selected_card_id": card_id,
                "pending": {
                    "flow": "agent",
                    "node": "dispute_pick",
                    "awaiting_slot": "transactions",
                },
            }
        )
        return "\n".join(refs.render(handle) for handle in handles)

    async def _tx_state_facts(tx: TxView) -> str:
        """Decline cause, Pending/Reversed state or plain details, by the row's own status."""
        update: dict[str, Any]
        if tx.status == "Declined":
            try:
                details = await bank_tools.get_card_details(tx.card_id)
            except NotFound:
                # Not on a card (a loan or account row): nothing a card tool can explain.
                return "no explanation available for this transaction."
            update = await _explain(flow_state, config, details, tx)
        elif tx.status in ("Pending", "Reversed"):
            update = await explain_tx(flow_state, config, tx)
        else:
            update = await _tx_details(flow_state, config, tx)
        facts: list[Fact] | None = update.get("facts")
        if not facts:
            return "no explanation available for this transaction."
        return refs.render(refs.add_tx(tx.tx_id, facts))

    async def explain_decline(args: BaseModel) -> str:
        a = cast(_DeclineArgs, args)
        if a.transaction is not None:
            tx_id = refs.tx_id(a.transaction)
            if tx_id is None:
                return _UNKNOWN_REF
            rows = await bank_tools.get_transactions_by_ids([tx_id])
            return await _tx_state_facts(rows[0]) if rows else _UNKNOWN_REF
        card_id: str | None = None
        if a.card is not None:
            card_id = refs.card_id(a.card)
            if card_id is None:
                return _NO_CARD_REF
        declines = await _card_rows(
            await bank_tools.search_transactions(TxFilter(card_id=card_id, status=["Declined"]))
        )
        if not declines:
            return "no declined transactions."
        if a.merchant_text is None and a.amount is None:
            return await _tx_state_facts(declines[0])
        matches = _filter_declines(declines, a.merchant_text, a.amount)
        if len(matches) == 1:
            return await _tx_state_facts(matches[0])
        return await _list_rows(matches or declines)

    async def scope_facts(args: BaseModel) -> str:
        topic = cast(_ScopeArgs, args).topic
        topics = get_policies().scope.topics
        entry = topics.get(topic)
        if entry is None:
            return "unknown topic; valid topics: " + ", ".join(sorted(topics))
        reason = _REASONS[entry.reason_key][language]
        values = {
            "topic_label": _TOPIC_LABELS[topic][language],
            "abstain_reason": reason,
            "closest_action": _closest_action(entry.closest_intents, language),
            # A topic a person cannot help with gets no human fact.
            "human_offer": _HUMAN_OFFERS[language] if entry.offer_human else "",
        }
        facts = [Fact(key=k, value=v, source=_SCOPE_SOURCE) for k, v in values.items() if v]
        refs.scope_topic = topic
        refs.scope_kind = entry.kind
        return refs.render(refs.add_group("scope", facts))

    return [
        LoopTool(
            "card_status",
            "Status, expiry and limits of one card, or of every card when no card is given.",
            _CardStatusArgs,
            card_status,
        ),
        LoopTool(
            "balance_due",
            "Balance, due date and minimum payment of a credit card.",
            _CardArgs,
            balance_due,
        ),
        LoopTool("debit_balance", "Available balance of a debit card.", _CardArgs, debit_balance),
        LoopTool(
            "search_transactions",
            "Find past movements by merchant, amount, date, card or status.",
            _SearchArgs,
            search_transactions,
        ),
        LoopTool(
            "dispute_candidates",
            "The charges of a card that can be disputed, offered to the customer to pick.",
            _CardArgs,
            dispute_candidates,
        ),
        LoopTool(
            "explain_decline",
            "Why a purchase was declined, or the state of a pending or reversed one.",
            _DeclineArgs,
            explain_decline,
        ),
        LoopTool(
            "scope_facts",
            "The facts for redirecting a request outside card support, by scope topic.",
            _ScopeArgs,
            scope_facts,
        ),
    ]
