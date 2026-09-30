"""The `unrecognized_charge` intent's flow node: dispute intake and fraud
triage (D4-B D7-D13, `02` §4.8).

`unrecognized_charge` stages itself on `pending.node`, the same shape every
other card-scoped flow uses: no slot yet (or `"card_select"`) runs the shared
`card_select` sub-flow first; `"transactions"` resumes the pick, reached only
through `TurnInput.selection` (`_entry`'s step 0, D7 -- `understand` never
runs on this turn, and the pick is never saved as a customer message);
`"card_possession"` and `"dispute_question"` resume the yes/no questions
(`nodes/route.py`'s affirm/deny slots, read through the same `decision()`
helper `replacement.py`'s offer question uses -- it isn't only for a plan's
button); `"confirm"` resumes the plan's confirm/cancel decision, for three
different plans that share this one `pending.node`
(`state["dispute"].compromise`/`.block_refused` tell them apart, see
`_resume_confirm`).

Every side effect goes through `flows/actions.py`, which is the one place
that reads `config["configurable"]["bank_write_tools"]` (R6). The Fraudes
handoff is not a write this module makes: it sets `escalation_reason`
(`disputes.yaml`'s `handoff.reason`), `handoff_queue`, `handoff_evidence` and
`handoff_open_questions`, and `graph._after_flow` routes the turn through
D4-A's `handoff_summary` -> `handoff` nodes, which build the packet from the
verified `actions`, persist it and emit `ui.handoff_banner` (with the claim's
case ids). This module never imports `app.core.llm`.
"""

from datetime import datetime
from typing import Any, cast

from langchain_core.runnables import RunnableConfig

from app.core.actions import ActionResult
from app.core.errors import ToolUnavailable
from app.domains.cards.schemas import BlockReason, CardDetails
from app.domains.conversation.fact_values import record
from app.domains.conversation.flows.actions import (
    StepSpec,
    decision,
    execute_plan,
    fill,
    start_plan,
)
from app.domains.conversation.flows.card_select import (
    Ask,
    Fallback,
    NoCards,
    card_picker_event,
    load_card_select_policy,
    select_card,
)
from app.domains.conversation.graph import GraphState
from app.domains.conversation.state import DisputeState, Fact
from app.domains.conversation.templates import Language, TemplateKind, get_template
from app.domains.conversation.tools import BankReadTools
from app.domains.conversation.tools.executor import ConfirmedWriteTools
from app.domains.conversation.ui import (
    TransactionListEvent,
    TransactionListPayload,
    TxOption,
)
from app.domains.handoff.schemas import HandoffEvidence
from app.domains.localization import mask_card
from app.domains.localization.format import Country, format_date, format_money, format_time
from app.domains.policy.disputes import load_disputes_policy
from app.domains.transactions.schemas import TxFilter, TxStatus, TxView

__all__ = ["unrecognized_charge"]

_MERCHANT_FALLBACK: dict[Language, str] = {
    "es": "Comercio",
    "pt": "Estabelecimento",
}

# `disputes.yaml`'s question ids -> the fixed ES/PT question text (spec
# §Contracts "policies/disputes.yaml": "the ES/PT question texts are
# templates (`dispute_q_<id>`), not YAML"). Both the possession question and
# the single-charge path's remaining questions are asked through this map.
_QUESTION_TEMPLATES: dict[str, TemplateKind] = {
    "card_in_possession": "dispute_q_card_in_possession",
    "contacted_merchant": "dispute_q_contacted_merchant",
}


async def unrecognized_charge(state: GraphState, config: RunnableConfig) -> dict[str, Any]:
    """Resolve which card, the candidate pick, the compromise/single-charge
    questions, then the confirmed write(s) (D8-D13)."""
    pending = state.get("pending")
    node = pending["node"] if pending is not None else None

    if node == "confirm":
        return await _resume_confirm(state, config)
    if node == "transactions":
        return await _resume_pick(state, config)
    if node == "card_possession":
        return await _resume_possession(state, config)
    if node == "dispute_question":
        return await _resume_question(state, config)
    return await _select_card(state, config)


async def _select_card(state: GraphState, config: RunnableConfig) -> dict[str, Any]:
    """Fresh turn, or a `card_hint` resume: the same `card_select` sub-flow
    `card_block`/`card_unlock`/`replacement` run, then the candidate pull below."""
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
        record(outcome.card_options)
        text = get_template("ask_which_card_dispute", language).replace(
            "{card_options}", outcome.card_options
        )
        return {
            "pending": {
                "flow": "unrecognized_charge",
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
    update.update(await _offer_candidates(state, config, outcome.card_id))
    return update


async def _offer_candidates(
    state: GraphState, config: RunnableConfig, card_id: str
) -> dict[str, Any]:
    """`transactions.search` over `disputes.yaml`'s `candidate_statuses`
    (D12): no candidates writes nothing and clears `pending`; otherwise
    `ui.transaction_list` pauses for the pick (D7, D13)."""
    bank_tools: BankReadTools = config["configurable"]["bank_tools"]
    language = state["language"]
    country = state["country"]
    policy = load_disputes_policy()

    try:
        details = await bank_tools.get_card_details(card_id)
        candidates = await bank_tools.search_transactions(
            TxFilter(card_id=card_id, status=cast(list[TxStatus], policy.candidate_statuses))
        )
    except ToolUnavailable:
        return {"escalation_reason": "tool_failure"}

    if not candidates:
        return {
            "pending": None,
            "dispute": None,
            "segments": [get_template("dispute_no_transactions", language)],
        }

    options = [_tx_option(tx, details.last4, country, language) for tx in candidates]
    prompt = fill(get_template("dispute_transactions_prompt", language), card_last4=details.last4)
    dispute: DisputeState = {
        "card_id": card_id,
        "offered_tx_ids": [tx.tx_id for tx in candidates],
        "fraud_scores": {tx.tx_id: tx.fraud_score for tx in candidates},
        "picked_tx_ids": [],
        "answers": [],
        "question_index": 0,
        "compromise": False,
        "block_refused": False,
    }
    return {
        "dispute": dispute,
        "pending": {
            "flow": "unrecognized_charge",
            "node": "transactions",
            "awaiting_slot": "transactions",
        },
        "segments": [prompt],
        "ui": [
            TransactionListEvent(
                kind="transaction_list",
                payload=TransactionListPayload(options=options, multi=True),
            )
        ],
    }


def _tx_option(tx: TxView, last4: str, country: Country, language: Language) -> TxOption:
    """`merchant · money · day-first date · •••• last4`, all formatted in
    code (D13, R4); a missing merchant uses the fixed fallback label."""
    merchant = tx.merchant_name or _MERCHANT_FALLBACK[language]
    label = (
        f"{merchant} · {format_money(tx.amount, tx.currency, country)} · "
        f"{format_date(tx.occurred_at.date())} · {mask_card(last4)}"
    )
    return TxOption(tx_id=tx.tx_id, label=label)


async def _resume_pick(state: GraphState, config: RunnableConfig) -> dict[str, Any]:
    """The pick itself (D7). The route already checks `selection.tx_ids`
    against `dispute.offered_tx_ids` before scheduling this turn (T8); this
    re-checks the same rule so the flow never trusts an id it didn't offer,
    whatever entry point reached it (R1)."""
    language = state["language"]
    dispute = state.get("dispute")
    selection = state.get("selection")
    if dispute is None or selection is None:
        return {"pending": None, "segments": [get_template("nothing_pending", language)]}

    offered = set(dispute["offered_tx_ids"])
    picked = [tx_id for tx_id in selection.tx_ids if tx_id in offered]
    if not picked:
        # Nothing offered was actually picked: the pause stays open.
        return {"segments": [get_template("pending_reminder", language)]}

    scores = [dispute["fraud_scores"].get(tx_id) for tx_id in picked]
    max_score = max((s for s in scores if s is not None), default=None)
    policy = load_disputes_policy()
    compromise = policy.triggers_compromise(len(picked), max_score)
    dispute = _replace(dispute, picked_tx_ids=picked, compromise=compromise)

    if compromise:
        return await _start_compromise_plan(state, config, dispute)
    return _ask_possession(state, dispute)


def _ask_possession(state: GraphState, dispute: DisputeState) -> dict[str, Any]:
    """D8: asked right after the pick, only when count/score haven't already
    triggered the compromise rule."""
    policy = load_disputes_policy()
    language = state["language"]
    return {
        "dispute": dispute,
        "pending": {
            "flow": "unrecognized_charge",
            "node": "card_possession",
            "awaiting_slot": "card_possession",
        },
        "segments": [get_template(_QUESTION_TEMPLATES[policy.possession_question], language)],
    }


async def _resume_possession(state: GraphState, config: RunnableConfig) -> dict[str, Any]:
    """ "no" triggers compromise; "sí" moves on to the single-charge path's
    remaining questions (D8). `policies/disputes.yaml`'s `questions[0]` is
    always the possession question itself, so the single-charge path resumes
    at index 1."""
    language = state["language"]
    dispute = state.get("dispute")
    if dispute is None:
        return {"pending": None, "segments": [get_template("nothing_pending", language)]}
    outcome = decision(state)
    if outcome not in ("confirm", "cancel"):
        return {"segments": [get_template("pending_reminder", language)]}

    policy = load_disputes_policy()
    answer = "yes" if outcome == "confirm" else "no"
    dispute = _replace(
        dispute, answers=[*dispute["answers"], f"{policy.possession_question}={answer}"]
    )

    if answer == "no":
        dispute = _replace(dispute, compromise=True)
        return await _start_compromise_plan(state, config, dispute)

    next_update = _ask_next_question(state, dispute, index=1)
    if next_update is not None:
        return next_update
    return await _start_claim_plan(state, config, dispute)


async def _resume_question(state: GraphState, config: RunnableConfig) -> dict[str, Any]:
    """A single-charge path question answered, one at a time (D8)."""
    language = state["language"]
    dispute = state.get("dispute")
    if dispute is None:
        return {"pending": None, "segments": [get_template("nothing_pending", language)]}
    outcome = decision(state)
    if outcome not in ("confirm", "cancel"):
        return {"segments": [get_template("pending_reminder", language)]}

    policy = load_disputes_policy()
    index = dispute["question_index"]
    answer = "yes" if outcome == "confirm" else "no"
    if index < len(policy.questions):
        question_id = policy.questions[index]
        dispute = _replace(dispute, answers=[*dispute["answers"], f"{question_id}={answer}"])

    next_update = _ask_next_question(state, dispute, index=index + 1)
    if next_update is not None:
        return next_update
    return await _start_claim_plan(state, config, dispute)


def _ask_next_question(
    state: GraphState, dispute: DisputeState, *, index: int
) -> dict[str, Any] | None:
    """Ask `disputes.yaml`'s `questions[index]`, or `None` once they're all
    answered (the caller then issues the one-step claim plan, D11)."""
    policy = load_disputes_policy()
    if index >= len(policy.questions):
        return None
    language = state["language"]
    question_id = policy.questions[index]
    dispute = _replace(dispute, question_index=index)
    return {
        "dispute": dispute,
        "pending": {
            "flow": "unrecognized_charge",
            "node": "dispute_question",
            "awaiting_slot": "dispute_question",
        },
        "segments": [get_template(_QUESTION_TEMPLATES[question_id], language)],
    }


async def _start_compromise_plan(
    state: GraphState, config: RunnableConfig, dispute: DisputeState
) -> dict[str, Any]:
    """D9's two-step plan: `cards.block_card`, then `disputes.create_claim`,
    under intent `unrecognized_charge`. An already-blocked card still keeps
    the block step (spec open item 4): it writes its own history row, same
    as any other `block_card` call, and the plan stays simple to read back."""
    bank_tools: BankReadTools = config["configurable"]["bank_tools"]
    language = state["language"]
    policy = load_disputes_policy()
    try:
        details = await bank_tools.get_card_details(dispute["card_id"])
        flags = await _priority_flags(bank_tools, dispute)
    except ToolUnavailable:
        return {"escalation_reason": "tool_failure"}

    tx_count = len(dispute["picked_tx_ids"])
    view_facts = [Fact(key="card_mask", value=mask_card(details.last4), source=details.source)]
    claim_facts = [Fact(key="tx_count", value=tx_count, source="conversation")]
    text = fill(
        get_template("dispute_confirm_compromise", language),
        card_last4=details.last4,
        tx_count=str(tx_count),
    )
    update = await start_plan(
        state,
        config,
        flow="unrecognized_charge",
        steps=[
            StepSpec(
                tool="cards.block_card",
                args={"card_id": details.card_id, "reason": policy.compromise.block_reason},
                summary_key="block_card",
                view_facts=view_facts,
            ),
            StepSpec(
                tool="disputes.create_claim",
                args={
                    "tx_ids": dispute["picked_tx_ids"],
                    "answers": sorted(dispute["answers"]),
                    "priority_flags": flags,
                },
                summary_key="create_claim",
                view_facts=claim_facts,
            ),
        ],
        text=text,
        intent="unrecognized_charge",
    )
    update["dispute"] = dispute
    update["priority_flags"] = flags
    return update


async def _start_claim_plan(
    state: GraphState, config: RunnableConfig, dispute: DisputeState
) -> dict[str, Any]:
    """D11's one-step plan: no block; a handoff on success only when a B2
    priority flag is set."""
    bank_tools: BankReadTools = config["configurable"]["bank_tools"]
    language = state["language"]
    try:
        flags = await _priority_flags(bank_tools, dispute)
    except ToolUnavailable:
        return {"escalation_reason": "tool_failure"}
    tx_count = len(dispute["picked_tx_ids"])
    claim_facts = [Fact(key="tx_count", value=tx_count, source="conversation")]
    text = fill(get_template("dispute_confirm_claim", language), tx_count=str(tx_count))
    update = await start_plan(
        state,
        config,
        flow="unrecognized_charge",
        steps=[
            StepSpec(
                tool="disputes.create_claim",
                args={
                    "tx_ids": dispute["picked_tx_ids"],
                    "answers": sorted(dispute["answers"]),
                    "priority_flags": flags,
                },
                summary_key="create_claim",
                view_facts=claim_facts,
            )
        ],
        text=text,
        intent="unrecognized_charge",
    )
    update["dispute"] = dispute
    update["priority_flags"] = flags
    return update


async def _offer_claim_only(
    state: GraphState, config: RunnableConfig, dispute: DisputeState
) -> dict[str, Any]:
    """D10: the block was refused; offers the claim alone as a new one-step
    plan, in the same turn as the refusal."""
    bank_tools: BankReadTools = config["configurable"]["bank_tools"]
    language = state["language"]
    try:
        flags = await _priority_flags(bank_tools, dispute)
    except ToolUnavailable:
        return {"escalation_reason": "tool_failure"}
    tx_count = len(dispute["picked_tx_ids"])
    claim_facts = [Fact(key="tx_count", value=tx_count, source="conversation")]
    text = fill(get_template("dispute_block_refused_offer_claim", language), tx_count=str(tx_count))
    update = await start_plan(
        state,
        config,
        flow="unrecognized_charge",
        steps=[
            StepSpec(
                tool="disputes.create_claim",
                args={
                    "tx_ids": dispute["picked_tx_ids"],
                    "answers": sorted(dispute["answers"]),
                    "priority_flags": flags,
                },
                summary_key="create_claim",
                view_facts=claim_facts,
            )
        ],
        text=text,
        intent="unrecognized_charge",
    )
    update["dispute"] = dispute
    update["priority_flags"] = flags
    return update


async def _resume_confirm(state: GraphState, config: RunnableConfig) -> dict[str, Any]:
    """The plan's confirm/cancel decision (D9-D11). `dispute["compromise"]`/
    `["block_refused"]` tell the two-step compromise plan, the claim-only
    plan issued after a refused block, and the single-charge one-step plan
    apart -- all three share this one `pending.node`."""
    language = state["language"]
    dispute = state.get("dispute")
    token_id = state.get("confirmation_token_id")
    if dispute is None or token_id is None:
        return {
            "pending": None,
            "confirmation_token_id": None,
            "segments": [get_template("nothing_pending", language)],
        }

    outcome = decision(state)
    if outcome == "cancel":
        return await _resume_cancel(state, config, dispute, token_id)
    if outcome != "confirm":
        # `"stale"` or `None`: nothing this turn matches the open plan.
        return {"segments": [get_template("nothing_pending", language)]}

    if dispute["compromise"] and not dispute["block_refused"]:
        return await _confirm_compromise_plan(state, config, dispute, token_id)
    return await _confirm_claim_plan(state, config, dispute, token_id)


async def _resume_cancel(
    state: GraphState, config: RunnableConfig, dispute: DisputeState, token_id: str
) -> dict[str, Any]:
    bank_write_tools: ConfirmedWriteTools = config["configurable"]["bank_write_tools"]
    language = state["language"]
    await bank_write_tools.cancel_plan(token_id)

    if dispute["compromise"] and not dispute["block_refused"]:
        # D10: the block was refused; nothing written. Offer the claim alone.
        return await _offer_claim_only(state, config, _replace(dispute, block_refused=True))

    if dispute["compromise"] and dispute["block_refused"]:
        # D10: the claim was refused too. Hand off to Fraudes with no claim.
        return _handoff_no_claim(state, dispute)

    return {
        "pending": None,
        "confirmation_token_id": None,
        "dispute": None,
        "segments": [get_template("action_cancelled", language)],
    }


async def _confirm_compromise_plan(
    state: GraphState, config: RunnableConfig, dispute: DisputeState, token_id: str
) -> dict[str, Any]:
    bank_tools: BankReadTools = config["configurable"]["bank_tools"]
    bank_write_tools: ConfirmedWriteTools = config["configurable"]["bank_write_tools"]
    policy = load_disputes_policy()
    details = await bank_tools.get_card_details(dispute["card_id"])
    tx_ids = dispute["picked_tx_ids"]
    answers = sorted(dispute["answers"])
    flags = sorted(state.get("priority_flags", []))
    block_reason = cast(BlockReason, policy.compromise.block_reason)

    async def block_call() -> ActionResult:
        return await bank_write_tools.block_card(details.card_id, block_reason, token_id)

    async def claim_call() -> ActionResult:
        return await bank_write_tools.create_claim(tx_ids, answers, flags, token_id)

    outcome = await execute_plan(state, config, [block_call, claim_call])
    if isinstance(outcome, dict):
        outcome["dispute"] = None
        return outcome

    block_result, claim_result = outcome
    return _compromise_success(state, dispute, details, block_result, claim_result)


def _compromise_success(
    state: GraphState,
    dispute: DisputeState,
    details: CardDetails,
    block_result: ActionResult,
    claim_result: ActionResult,
) -> dict[str, Any]:
    language = state["language"]
    country = state["country"]
    case_ids = claim_result.case_ids or []

    at = block_result.readback.get("at")
    time_text = format_time(at, country) if isinstance(at, datetime) else ""
    text = fill(
        get_template("dispute_claim_opened", language),
        card_last4=details.last4,
        case_ids=", ".join(case_ids),
        time=time_text,
    )

    return {
        "actions": [block_result, claim_result],
        "pending": None,
        "confirmation_token_id": None,
        "dispute": None,
        "segments": [text],
        **_fraud_handoff(state, dispute, []),
    }


async def _confirm_claim_plan(
    state: GraphState, config: RunnableConfig, dispute: DisputeState, token_id: str
) -> dict[str, Any]:
    """The claim-only plan, either D10's (after a refused block) or D11's
    (single charge, `dispute["block_refused"]` stays `False`)."""
    bank_write_tools: ConfirmedWriteTools = config["configurable"]["bank_write_tools"]
    tx_ids = dispute["picked_tx_ids"]
    answers = sorted(dispute["answers"])
    flags = sorted(state.get("priority_flags", []))

    async def claim_call() -> ActionResult:
        return await bank_write_tools.create_claim(tx_ids, answers, flags, token_id)

    outcome = await execute_plan(state, config, [claim_call])
    if isinstance(outcome, dict):
        outcome["dispute"] = None
        return outcome

    (claim_result,) = outcome
    if dispute["block_refused"]:
        return _claim_only_success(state, dispute, claim_result)
    return _single_charge_success(state, dispute, claim_result)


def _claim_only_success(
    state: GraphState, dispute: DisputeState, claim_result: ActionResult
) -> dict[str, Any]:
    """D10: the claim confirmed after the block was refused -- case id, plus
    a Fraudes handoff noting the card is still active."""
    language = state["language"]
    text = _claim_reply_text(state, claim_result)

    return {
        "actions": [claim_result],
        "pending": None,
        "confirmation_token_id": None,
        "dispute": None,
        "segments": [text],
        **_fraud_handoff(
            state, dispute, [get_template("dispute_open_question_card_active", language)]
        ),
    }


def _single_charge_success(
    state: GraphState, dispute: DisputeState, claim_result: ActionResult
) -> dict[str, Any]:
    """D11: the case id, and nothing else -- no handoff. With a B2 priority
    flag (D6) the verified claim is followed by a Reclamos handoff; the reply
    keeps the claim's own segment."""
    update: dict[str, Any] = {
        "actions": [claim_result],
        "pending": None,
        "confirmation_token_id": None,
        "dispute": None,
        "segments": [_claim_reply_text(state, claim_result)],
    }
    if state.get("priority_flags"):
        handoff = load_disputes_policy().priority.handoff
        update["escalation_reason"] = handoff.reason
        update["handoff_queue"] = handoff.queue
        update["handoff_evidence"] = _evidence(dispute)
        update["handoff_open_questions"] = _flag_lines(state)
    return update


def _handoff_no_claim(state: GraphState, dispute: DisputeState) -> dict[str, Any]:
    """D10: both the block and the claim were refused. Still a Fraudes
    handoff, with no claim and both refusals in `open_questions`."""
    language = state["language"]
    return {
        "pending": None,
        "confirmation_token_id": None,
        "dispute": None,
        "segments": [get_template("dispute_handoff_no_claim", language)],
        **_fraud_handoff(
            state,
            dispute,
            [
                get_template("dispute_open_question_card_active", language),
                get_template("dispute_open_question_claim_refused", language),
            ],
        ),
    }


def _fraud_handoff(
    state: GraphState, dispute: DisputeState, open_questions: list[str]
) -> dict[str, Any]:
    """The state keys that send this turn to D4-A's handoff nodes (D9, D10):
    `disputes.yaml`'s reason and queue, the picked transactions as evidence
    and the code-filled open questions, plus one line per B2 priority flag
    (D7: the queue stays Fraudes, the flags only annotate the packet). The
    packet, `mode = human` and the banner are the `handoff` node's job."""
    policy = load_disputes_policy()
    return {
        "escalation_reason": policy.handoff.reason,
        "handoff_queue": policy.handoff.queue,
        "handoff_evidence": _evidence(dispute),
        "handoff_open_questions": [*open_questions, *_flag_lines(state)],
    }


async def _priority_flags(bank_tools: BankReadTools, dispute: DisputeState) -> list[str]:
    """B2's sorted `priority_flags`, built in code before any claim plan is
    issued (R2: the signed plan carries them, the LLM never does). The two
    complaint signals come from one customer-scoped read; the amount flag from
    the picked rows' own `amount`/`currency` through the policy's method (R8).
    Raises `ToolUnavailable`; the caller takes the `tool_failure` path."""
    policy = load_disputes_policy()
    signals = await bank_tools.get_priority_signals()
    flags: list[str] = []
    if signals.repeat_complainer:
        flags.append("repeat_complainer")
    if signals.open_critical:
        flags.append("open_critical")
    # The picked ids are a subset of the offered ones, so the same search the
    # offer ran returns their rows (at most 10, `transactions.search`).
    rows = await bank_tools.search_transactions(
        TxFilter(card_id=dispute["card_id"], status=cast(list[TxStatus], policy.candidate_statuses))
    )
    picked = set(dispute["picked_tx_ids"])
    if any(
        policy.amount_over_threshold(tx.amount, tx.currency) for tx in rows if tx.tx_id in picked
    ):
        flags.append("amount_over_threshold")
    return sorted(flags)


def _flag_lines(state: GraphState) -> list[str]:
    """One fixed agent-facing line per priority flag, for `open_questions`."""
    language = state["language"]
    return [
        get_template(cast(TemplateKind, f"priority_flag_{flag}"), language)
        for flag in sorted(state.get("priority_flags", []))
    ]


def _claim_reply_text(state: GraphState, claim_result: ActionResult) -> str:
    language = state["language"]
    country = state["country"]
    case_ids = claim_result.case_ids or []
    at = claim_result.readback.get("at")
    time_text = format_time(at, country) if isinstance(at, datetime) else ""
    return fill(
        get_template("dispute_claim_opened_single", language),
        case_ids=", ".join(case_ids),
        time=time_text,
    )


def _evidence(dispute: DisputeState) -> list[HandoffEvidence]:
    return [
        HandoffEvidence(
            type="transaction", ref=tx_id, fraud_score=dispute["fraud_scores"].get(tx_id)
        )
        for tx_id in dispute["picked_tx_ids"]
    ]


def _replace(dispute: DisputeState, **changes: Any) -> DisputeState:
    """A shallow-updated copy of `dispute` (a `TypedDict`): never mutates the
    checkpointed value in place."""
    return cast(DisputeState, {**dispute, **changes})
