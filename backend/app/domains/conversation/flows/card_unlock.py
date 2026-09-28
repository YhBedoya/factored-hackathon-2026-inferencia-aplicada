"""The `card_unlock` intent's flow node: undo a lock or block, or hand off
what the customer can't self-service (D12, `02` §4.7).

`card_unlock` stages itself on `pending.node`, same shape as `card_block`:
no slot yet (or `"card_select"`) runs the shared `card_select` sub-flow
first; `"otp"` resumes the step-up pause (D1) -- only ever reached through
`resume="step_up"`, never a typed message, since `route.py`'s `_answer_fits`
has no `"otp"` case; `"confirm"` resumes the plan's confirm/cancel decision
(D14).

`get_block_origin` decides everything past `card_select` (D8): a lock made
in this session needs step-up before a plan can even be issued, a permanent
block can't be undone and offers a replacement instead (the same offer
`card_block` makes after its own verified block, D11), a bank-side block
hands off to the queue `policies/escalation.yaml` names for its reason (D9),
and "none" says there is nothing to undo. A customer who isn't Active is
refused before any of that -- unlock is not in `escalation.yaml`'s
`customer_not_active.allowed` list (D10).

Every side effect goes through `flows/actions.py`, which is the one place
that reads `config["configurable"]["bank_write_tools"]`; this module never
imports `app.core.llm` (R6).
"""

from typing import Any

from langchain_core.runnables import RunnableConfig

from app.core.actions import ActionResult
from app.core.errors import ToolUnavailable
from app.domains.conversation.flows.actions import (
    cancel,
    decision,
    execute,
    fill,
    handoff,
    otp_pause,
    start_plan,
)
from app.domains.conversation.flows.card_select import (
    Ask,
    Fallback,
    NoCards,
    ask_which_card_text,
    load_card_select_policy,
    select_card,
)
from app.domains.conversation.graph import GraphState
from app.domains.conversation.state import Fact
from app.domains.conversation.templates import Language, get_template
from app.domains.conversation.tools import BankReadTools
from app.domains.conversation.tools.executor import ConfirmedWriteTools
from app.domains.localization import mask_card
from app.domains.policy.escalation import load_escalation_policy

__all__ = ["card_unlock"]


_UNLOCK_ACTION_LABEL: dict[Language, str] = {
    "es": "desbloquear",
    "pt": "desbloquear",
}
_UNLOCK_EFFECT_LABEL: dict[Language, str] = {
    "es": "Vas a poder volver a usarla con normalidad.",
    "pt": "Você vai poder voltar a usá-lo normalmente.",
}
_UNLOCK_STATE_LABEL: dict[Language, str] = {
    "es": "desbloqueada",
    "pt": "desbloqueado",
}


async def card_unlock(state: GraphState, config: RunnableConfig) -> dict[str, Any]:
    """Resolve which card, then its block origin, then the confirmed write (D12)."""
    pending = state.get("pending")
    node = pending["node"] if pending is not None else None

    if node == "confirm":
        return await _resume_confirm(state, config)
    if node == "otp":
        return await _resume_otp(state, config)
    return await _select_card(state, config)


async def _select_card(state: GraphState, config: RunnableConfig) -> dict[str, Any]:
    """Fresh turn, or a `card_hint` resume: the same `card_select` sub-flow
    `card_block` runs (D12), then the origin check below."""
    bank_tools: BankReadTools = config["configurable"]["bank_tools"]
    language = state["language"]
    nlu = state.get("nlu")
    hint = nlu.slots.card_hint if nlu is not None else None
    failures = state.get("clarification_failures", 0)

    try:
        cards = await bank_tools.list_cards()
    except ToolUnavailable:
        return {"escalation_reason": "tool_unavailable"}

    policy = load_card_select_policy()
    outcome = select_card(cards, hint, failures, policy, language)

    if isinstance(outcome, Ask):
        return {
            "pending": {"flow": "card_unlock", "node": "card_select", "awaiting_slot": "card_hint"},
            "clarification_failures": outcome.failures,
            "segments": [ask_which_card_text("unlock", outcome, language)],
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
    update.update(await _check_status_and_origin(state, config, outcome.card_id))
    return update


async def _check_status_and_origin(
    state: GraphState, config: RunnableConfig, card_id: str
) -> dict[str, Any]:
    """The `customer_not_active` refusal first (D10), then `get_block_origin`'s
    four outcomes (D8, D9, D11)."""
    bank_tools: BankReadTools = config["configurable"]["bank_tools"]
    bank_write_tools: ConfirmedWriteTools = config["configurable"]["bank_write_tools"]
    language = state["language"]
    escalation = load_escalation_policy()

    try:
        profile = await bank_tools.get_profile()
    except ToolUnavailable:
        return {"escalation_reason": "tool_unavailable"}

    not_active = escalation.customer_not_active
    if profile.customer_status in not_active.statuses and "unlock_card" not in not_active.allowed:
        return handoff(not_active.queue, "customer_not_active", language)

    try:
        origin = await bank_write_tools.get_block_origin(card_id, "card_unlock")
    except ToolUnavailable:
        return {"escalation_reason": "tool_unavailable"}

    if origin.kind == "customer_lock":
        if await bank_write_tools.is_step_up_valid():
            return await _start_unlock_plan(state, config, card_id)
        return otp_pause("card_unlock", "otp", "cards.unlock_card", language)

    if origin.kind == "customer_block":
        try:
            details = await bank_tools.get_card_details(card_id)
        except ToolUnavailable:
            return {"escalation_reason": "tool_unavailable"}
        no_undo = fill(get_template("block_permanent_no_undo", language), card_last4=details.last4)
        offer = fill(get_template("offer_replacement", language), card_last4=details.last4)
        return {
            "pending": {
                "flow": "replacement",
                "node": "offer",
                "awaiting_slot": "offer_replacement",
            },
            "segments": [no_undo, offer],
        }

    if origin.kind == "bank_side":
        side = escalation.bank_side_queues
        if origin.reason == "past_due":
            return handoff(side.past_due, "bank_side_block", language)
        if origin.reason == "fraud":
            return handoff(side.fraud, "bank_side_block", language)
        if origin.reason == "bank_status":
            return handoff(side.bank_status, "bank_side_block", language)
        return handoff(side.customer_status, "bank_side_block", language)

    # "none": nothing to undo.
    return {"pending": None, "segments": [get_template("not_blocked", language)]}


async def _resume_otp(state: GraphState, config: RunnableConfig) -> dict[str, Any]:
    """The step-up resume (D1): reached only through `resume="step_up"`."""
    bank_write_tools: ConfirmedWriteTools = config["configurable"]["bank_write_tools"]
    language = state["language"]
    card_id = state.get("selected_card_id")
    if card_id is None:
        return {"pending": None, "segments": [get_template("nothing_pending", language)]}
    if await bank_write_tools.is_step_up_valid():
        return await _start_unlock_plan(state, config, card_id)
    # Still invalid: pause again, nothing issued (D1).
    return otp_pause("card_unlock", "otp", "cards.unlock_card", language)


async def _start_unlock_plan(
    state: GraphState, config: RunnableConfig, card_id: str
) -> dict[str, Any]:
    bank_tools: BankReadTools = config["configurable"]["bank_tools"]
    language = state["language"]
    try:
        details = await bank_tools.get_card_details(card_id)
    except ToolUnavailable:
        return {"escalation_reason": "tool_unavailable"}

    view_facts = [Fact(key="card_mask", value=mask_card(details.last4), source=details.source)]
    confirm_values = {
        "action": _UNLOCK_ACTION_LABEL[language],
        "effect": _UNLOCK_EFFECT_LABEL[language],
        "card_last4": details.last4,
    }
    return await start_plan(
        state,
        config,
        flow="card_unlock",
        tool="cards.unlock_card",
        args={"card_id": details.card_id},
        summary_key="unlock_card",
        view_facts=view_facts,
        confirm_values=confirm_values,
        intent="card_unlock",
    )


async def _resume_confirm(state: GraphState, config: RunnableConfig) -> dict[str, Any]:
    """The plan's confirm/cancel decision (D14)."""
    language = state["language"]
    outcome = decision(state)
    if outcome == "cancel":
        return await cancel(state, config)
    if outcome != "confirm":
        # `"stale"` or `None`: nothing this turn matches the open plan.
        return {"segments": [get_template("nothing_pending", language)]}

    card_id = state.get("selected_card_id")
    token_id = state.get("confirmation_token_id")
    if card_id is None or token_id is None:
        return {
            "pending": None,
            "confirmation_token_id": None,
            "segments": [get_template("nothing_pending", language)],
        }

    bank_tools: BankReadTools = config["configurable"]["bank_tools"]
    bank_write_tools: ConfirmedWriteTools = config["configurable"]["bank_write_tools"]
    details = await bank_tools.get_card_details(card_id)

    async def call(card_id: str = card_id, token_id: str = token_id) -> ActionResult:
        return await bank_write_tools.unlock_card(card_id, token_id)

    return await execute(
        state,
        config,
        call,
        done_template="action_done_noref",
        done_values={"result": _UNLOCK_STATE_LABEL[language]},
        card_last4=details.last4,
    )
