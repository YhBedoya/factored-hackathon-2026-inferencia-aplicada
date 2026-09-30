"""The `card_block` intent's flow node: lock or block a card (D11, `02` §4.6).

`card_block` stages itself on `pending.awaiting_slot`, same shape as
`card_info`/`card_select`: no slot yet (or `"card_hint"`) runs `card_select`
first; `"block_kind"` resumes the lock-vs-block clarification; `"confirm"`
resumes the plan's confirm/cancel decision. `block_kind` is read from this
turn's fresh NLU slot when there is one, else from `state["slots"]` (written
here once resolved) -- a resumed "confirm" turn's own NLU only ever carries
`affirm`/`deny`, never `block_kind` again, so the flow has to remember which
kind it planned across that turn boundary.

Every side effect goes through `flows/actions.py`, which is the one place
that reads `config["configurable"]["bank_write_tools"]`; this module never
imports `app.core.llm` (R6).
"""

from typing import Any, Literal

from langchain_core.runnables import RunnableConfig

from app.core.actions import ActionResult
from app.core.errors import ToolUnavailable
from app.domains.cards.schemas import CardDetails
from app.domains.conversation.flows.actions import (
    StepSpec,
    cancel,
    decision,
    execute,
    fill,
    start_plan,
)
from app.domains.conversation.flows.card_select import (
    Ask,
    Fallback,
    NoCards,
    ask_which_card_text,
    card_picker_event,
    load_card_select_policy,
    select_card,
)
from app.domains.conversation.graph import GraphState
from app.domains.conversation.schemas import NLUSlots
from app.domains.conversation.state import Fact
from app.domains.conversation.templates import Language, get_template
from app.domains.conversation.tools import BankReadTools
from app.domains.conversation.tools.executor import ConfirmedWriteTools
from app.domains.conversation.ui import PickerOption, QuickRepliesEvent, QuickRepliesPayload
from app.domains.localization import mask_card, status_label

__all__ = ["card_block"]


BlockKind = Literal["temporary_lock", "permanent_block"]

# R11: bounded retries, same limit `card_select.py` uses for the card-hint
# clarification -- there is no policy-file field for it (D11 only names
# "the card_select.yaml limit"; the file itself carries no such number).
_MAX_BLOCK_KIND_FAILURES = 2

_LOCK_STATE_LABEL: dict[Language, str] = {
    "es": "bloqueada temporalmente",
    "pt": "bloqueado temporariamente",
}
_BLOCK_STATE_LABEL: dict[Language, str] = {
    "es": "bloqueada de forma permanente",
    "pt": "bloqueado de forma permanente",
}
_LOCK_ACTION_LABEL: dict[Language, str] = {
    "es": "bloquear temporalmente",
    "pt": "bloquear temporariamente",
}
_BLOCK_ACTION_LABEL: dict[Language, str] = {
    "es": "bloquear de forma permanente",
    "pt": "bloquear de forma permanente",
}
_LOCK_EFFECT: dict[Language, str] = {
    "es": "Vas a poder desbloquearla cuando quieras.",
    "pt": "Você vai poder desbloqueá-lo quando quiser.",
}
_BLOCK_EFFECT: dict[Language, str] = {
    "es": "Este bloqueo no se puede deshacer.",
    "pt": "Esse bloqueio não pode ser desfeito.",
}
# `ui.quick_replies` labels for `clarify_lock_vs_block` (D4, R4). Worded from
# the lock/block lexicon above, never "cancelar": `card_cancel` (Stretch) and
# `deny` are separate intents, and the word would collide with them.
_TEMPORARY_LOCK_LABEL: dict[Language, str] = {
    "es": "Bloqueo temporal",
    "pt": "Bloqueio temporário",
}
_PERMANENT_BLOCK_LABEL: dict[Language, str] = {
    "es": "Reportar pérdida o robo",
    "pt": "Reportar perda ou roubo",
}


async def card_block(state: GraphState, config: RunnableConfig) -> dict[str, Any]:
    """Resolve which card, which kind, then run the confirmed write (D11)."""
    pending = state.get("pending")
    node = pending["node"] if pending is not None else None

    if node == "confirm":
        return await _resume_confirm(state, config)
    if node == "block_kind":
        return await _resume_block_kind(state, config)
    return await _select_card(state, config)


async def _select_card(state: GraphState, config: RunnableConfig) -> dict[str, Any]:
    """Fresh turn, or a `card_hint` resume: same `card_select` sub-flow
    `card_info` runs (D12), then the block-kind check below.

    A fresh turn's `block_kind` can arrive before the card is resolved (e.g.
    "block my credit card, just a temporary lock" with several credit cards).
    When the card is still ambiguous that `block_kind` has to survive into the
    `card_hint` resume turn, whose own NLU only ever carries the card hint
    (B4 fix) -- so it is remembered in `state["slots"]` the same way
    `_check_state_and_plan` remembers it once the card is picked. A fresh
    NLU `block_kind` always wins over the remembered one.
    """
    bank_tools: BankReadTools = config["configurable"]["bank_tools"]
    language = state["language"]
    nlu = state.get("nlu")
    hint = nlu.slots.card_hint if nlu is not None else None
    nlu_block_kind: BlockKind | None = nlu.slots.block_kind if nlu is not None else None
    remembered_slots = state.get("slots")
    remembered_block_kind = remembered_slots.block_kind if remembered_slots is not None else None
    block_kind = nlu_block_kind if nlu_block_kind is not None else remembered_block_kind
    failures = state.get("clarification_failures", 0)

    try:
        cards = await bank_tools.list_cards()
    except ToolUnavailable:
        return {"escalation_reason": "tool_failure"}

    policy = load_card_select_policy()
    outcome = select_card(cards, hint, failures, policy, language)

    if isinstance(outcome, Ask):
        update: dict[str, Any] = {
            "pending": {"flow": "card_block", "node": "card_select", "awaiting_slot": "card_hint"},
            "clarification_failures": outcome.failures,
            "segments": [ask_which_card_text("block", outcome, language)],
            "ui": [card_picker_event(outcome)],
        }
        if block_kind is not None:
            update["slots"] = NLUSlots(block_kind=block_kind)
        return update
    if isinstance(outcome, NoCards):
        return {"escalation_reason": "no_cards", "pending": None, "clarification_failures": 0}
    if isinstance(outcome, Fallback):
        return {
            "escalation_reason": "clarification_exhausted",
            "pending": None,
            "clarification_failures": 0,
        }

    # Selected: `block_kind` is either this turn's own or the one remembered
    # across the ask-which-card question above.
    update = {"selected_card_id": outcome.card_id, "clarification_failures": 0}
    if block_kind is None:
        update.update(_ask_block_kind(state, failures=0))
        return update
    plan_update = await _check_state_and_plan(state, config, outcome.card_id, block_kind)
    update.update(plan_update)
    return update


async def _resume_block_kind(state: GraphState, config: RunnableConfig) -> dict[str, Any]:
    """A resumed turn answering `lock_vs_block` (D11)."""
    nlu = state.get("nlu")
    block_kind: BlockKind | None = nlu.slots.block_kind if nlu is not None else None
    if block_kind is None:
        slots = state.get("slots")
        block_kind = slots.block_kind if slots is not None else None
    card_id = state.get("selected_card_id")
    if block_kind is None or card_id is None:
        return _ask_block_kind(state, failures=state.get("clarification_failures", 0))
    return await _check_state_and_plan(state, config, card_id, block_kind)


def _ask_block_kind(state: GraphState, *, failures: int) -> dict[str, Any]:
    language = state["language"]
    new_failures = failures + 1
    if new_failures >= _MAX_BLOCK_KIND_FAILURES:
        return {
            "escalation_reason": "clarification_exhausted",
            "pending": None,
            "clarification_failures": 0,
        }
    options = [
        PickerOption(label=_TEMPORARY_LOCK_LABEL[language]),
        PickerOption(label=_PERMANENT_BLOCK_LABEL[language]),
    ]
    return {
        "pending": {"flow": "card_block", "node": "block_kind", "awaiting_slot": "block_kind"},
        "clarification_failures": new_failures,
        "segments": [get_template("clarify_lock_vs_block", language)],
        "ui": [
            QuickRepliesEvent(
                kind="quick_replies",
                payload=QuickRepliesPayload(slot="block_kind", options=options),
            )
        ],
    }


async def _check_state_and_plan(
    state: GraphState, config: RunnableConfig, card_id: str, block_kind: BlockKind
) -> dict[str, Any]:
    """The policy check (already Blocked/Closed/locked), else start the plan
    (D11). `block_kind` is remembered in `state["slots"]` so the "confirm"
    resume, whose own NLU only ever carries affirm/deny, still knows which
    tool to call.
    """
    bank_tools: BankReadTools = config["configurable"]["bank_tools"]
    language = state["language"]
    try:
        details = await bank_tools.get_card_details(card_id)
    except ToolUnavailable:
        return {"escalation_reason": "tool_failure"}

    already = _already_state_label(details, block_kind, language)
    if already is not None:
        text = fill(
            get_template("already_in_state", language), card_last4=details.last4, state=already
        )
        return {"pending": None, "clarification_failures": 0, "segments": [text]}

    update = await _start_block_plan(state, config, details, block_kind)
    update["slots"] = NLUSlots(block_kind=block_kind)
    return update


def _already_state_label(
    details: CardDetails, block_kind: BlockKind, language: Language
) -> str | None:
    if details.status in ("Blocked", "Closed"):
        return status_label(details.status, language)
    if block_kind == "temporary_lock" and details.locked:
        return _LOCK_STATE_LABEL[language]
    return None


async def _start_block_plan(
    state: GraphState, config: RunnableConfig, details: CardDetails, block_kind: BlockKind
) -> dict[str, Any]:
    language = state["language"]
    if block_kind == "temporary_lock":
        tool = "cards.lock_card"
        args: dict[str, Any] = {"card_id": details.card_id}
        confirm_values = {
            "action": _LOCK_ACTION_LABEL[language],
            "effect": _LOCK_EFFECT[language],
            "card_last4": details.last4,
        }
        summary_key = "lock_card"
    else:
        tool = "cards.block_card"
        args = {"card_id": details.card_id, "reason": "lost_or_stolen"}
        confirm_values = {
            "action": _BLOCK_ACTION_LABEL[language],
            "effect": _BLOCK_EFFECT[language],
            "card_last4": details.last4,
        }
        summary_key = "block_card"

    view_facts = [Fact(key="card_mask", value=mask_card(details.last4), source=details.source)]
    text = fill(get_template("action_confirm", language), **dict(confirm_values))
    return await start_plan(
        state,
        config,
        flow="card_block",
        steps=[StepSpec(tool=tool, args=args, summary_key=summary_key, view_facts=view_facts)],
        text=text,
        intent="card_block",
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
    slots = state.get("slots")
    block_kind = slots.block_kind if slots is not None else None
    token_id = state.get("confirmation_token_id")
    if card_id is None or block_kind is None or token_id is None:
        return {
            "pending": None,
            "confirmation_token_id": None,
            "segments": [get_template("nothing_pending", language)],
        }

    bank_tools: BankReadTools = config["configurable"]["bank_tools"]
    bank_write_tools: ConfirmedWriteTools = config["configurable"]["bank_write_tools"]
    details = await bank_tools.get_card_details(card_id)

    if block_kind == "temporary_lock":
        result_label = _LOCK_STATE_LABEL[language]

        async def call(card_id: str = card_id, token_id: str = token_id) -> ActionResult:
            return await bank_write_tools.lock_card(card_id, token_id)
    else:
        result_label = _BLOCK_STATE_LABEL[language]

        async def call(card_id: str = card_id, token_id: str = token_id) -> ActionResult:
            return await bank_write_tools.block_card(card_id, "lost_or_stolen", token_id)

    update = await execute(
        state,
        config,
        call,
        done_template="action_done_noref",
        done_values={"result": result_label},
        card_last4=details.last4,
    )

    if block_kind == "permanent_block" and "actions" in update:
        offer = fill(get_template("offer_replacement", language), card_last4=details.last4)
        update["segments"] = [*update["segments"], offer]
        update["pending"] = {
            "flow": "replacement",
            "node": "offer",
            "awaiting_slot": "offer_replacement",
        }

    return update
