"""The `replacement` intent's flow node: order a new card (D13, `02` §4.9).

`replacement` stages itself on `pending.node`, same shape as `card_block`/
`card_unlock`: no slot yet (or `"card_select"`) runs the shared `card_select`
sub-flow first; `"offer"` resumes the affirm/deny to the offer `card_block`
(D11) or `card_unlock` (D12) already made after their own verified write --
this module never re-emits that offer, only reads the answer; `"address_confirm"`
resumes the "send it to the address on file?" question (D4, D13);
`"otp"` resumes the step-up pause (D1) needed only for a new address;
`"address"` is reached only through `_entry`'s `awaiting_slot == "address"`
routing (D4, never a typed message through `understand`); `"confirm"`
resumes the plan's confirm/cancel decision (D14).

A card is eligible for a replacement only when its block origin is in the
policy's `replacement.eligible_origins` (`customer_block`) or the card is
already past its expiry (D13). `_select_card` computes that set first, so the
picker only lists eligible cards; a card the customer names that isn't
eligible gets the block offer or a person instead of a dead-end refusal. The
guard in `_check_active_and_eligibility` stays for the offer-resume path.

A new delivery address needs step-up first
(`policies/tools.yaml`'s `when_address_changed`, D2); the on-file address
does not. The raw address text is captured only in the `"address"` turn and
never leaves this module except as `vault.put_address`'s opaque
`"⟨ADDR_n⟩"` token -- it is never written to `slots`, `facts`, `PlanStep.args`
or the `ui` payload (R5).

Every side effect goes through `flows/actions.py`, which is the one place
that reads `config["configurable"]["bank_write_tools"]`; this module never
imports `app.core.llm` (R6).
"""

from typing import Any

from langchain_core.runnables import RunnableConfig

from app.core.actions import ActionResult
from app.core.errors import ToolUnavailable
from app.domains.conversation.flows.actions import (
    OFFER_BLOCK_PAUSE,
    StepSpec,
    cancel,
    closing,
    decision,
    execute,
    fill,
    handoff,
    offer,
    otp_pause,
    start_plan,
    with_closing,
)
from app.domains.conversation.flows.card_select import (
    Ask,
    Fallback,
    NoCards,
    ask_which_card_text,
    card_picker_event,
    load_card_select_policy,
    next_step_offer_kind,
    select_card,
)
from app.domains.conversation.graph import GraphState
from app.domains.conversation.schemas import NLUSlots
from app.domains.conversation.state import Fact, mark_segment
from app.domains.conversation.templates import Language, get_template
from app.domains.conversation.tools import BankReadTools
from app.domains.conversation.tools.executor import ConfirmedWriteTools
from app.domains.localization import local_today, mask_card
from app.domains.policy.escalation import load_escalation_policy, rule_queue
from app.domains.safety.vault import AddressVault

__all__ = ["replacement"]


_REPLACEMENT_ACTION_LABEL: dict[Language, str] = {
    "es": "pedir tu tarjeta nueva",
    "pt": "pedir seu cartão novo",
}
_REPLACEMENT_EFFECT_LABEL: dict[Language, str] = {
    "es": "La vas a recibir en los próximos días en la dirección que confirmamos.",
    "pt": "Você vai recebê-lo nos próximos dias no endereço que confirmamos.",
}
_REPLACEMENT_STATE_LABEL: dict[Language, str] = {
    "es": "pedida",
    "pt": "pedido",
}


async def replacement(state: GraphState, config: RunnableConfig) -> dict[str, Any]:
    """Resolve which card, then eligibility, address and the confirmed write (D13)."""
    pending = state.get("pending")
    node = pending["node"] if pending is not None else None

    if node == "confirm":
        return await _resume_confirm(state, config)
    if node == "address":
        return await _resume_address(state, config)
    if node == "otp":
        return await _resume_otp(state, config)
    if node == "address_confirm":
        return await _resume_address_confirm(state, config)
    if node == "offer":
        return await _resume_offer(state, config)
    return await _select_card(state, config)


async def _select_card(state: GraphState, config: RunnableConfig) -> dict[str, Any]:
    """Fresh turn, or a `card_hint` resume: the same `card_select` sub-flow
    `card_block`/`card_unlock` run, then the eligibility check below."""
    bank_tools: BankReadTools = config["configurable"]["bank_tools"]
    bank_write_tools: ConfirmedWriteTools = config["configurable"]["bank_write_tools"]
    language = state["language"]
    nlu = state.get("nlu")
    hint = nlu.slots.card_hint if nlu is not None else None
    failures = state.get("clarification_failures", 0)

    try:
        cards = await bank_tools.list_cards()
    except ToolUnavailable:
        return {"escalation_reason": "tool_failure"}

    policy = load_card_select_policy()
    open_cards = [card for card in cards if card.status != "Closed"]
    # Origin is read only for Blocked/locked cards: an Active card has none to read.
    origins: dict[str, str] = {}
    eligible: set[str] = set()
    try:
        for card in open_cards:
            origin_kind = "none"
            if card.status == "Blocked" or card.locked:
                origin = await bank_write_tools.get_block_origin(
                    card.card_id, "replacement_request"
                )
                origin_kind = origin.kind
            origins[card.card_id] = origin_kind
            if origin_kind in policy.replacement.eligible_origins:
                eligible.add(card.card_id)
                continue
            details = await bank_tools.get_card_details(card.card_id)
            if details.expiration_date is not None and details.expiration_date < local_today(
                state["country"]
            ):
                eligible.add(card.card_id)
    except ToolUnavailable:
        return {"escalation_reason": "tool_failure"}

    outcome = select_card(
        cards,
        hint,
        failures,
        policy,
        language,
        focus_card_id=state.get("selected_card_id"),
        candidate_ids=frozenset(eligible),
    )

    if isinstance(outcome, Ask):
        return {
            "pending": {"flow": "replacement", "node": "card_select", "awaiting_slot": "card_hint"},
            "clarification_failures": outcome.failures,
            "segments": [ask_which_card_text("replacement", outcome, language)],
            "ui": [card_picker_event(outcome)],
        }
    if isinstance(outcome, NoCards):
        if not open_cards:
            return {"escalation_reason": "no_cards", "pending": None, "clarification_failures": 0}
        # Cards exist but none can be replaced yet: offer the block that unlocks it.
        return {
            "pending": OFFER_BLOCK_PAUSE,
            "clarification_failures": 0,
            "segments": [get_template("replacement_needs_block", language)],
        }
    if isinstance(outcome, Fallback):
        return {
            "escalation_reason": "clarification_exhausted",
            "pending": None,
            "clarification_failures": 0,
        }

    update: dict[str, Any] = {"selected_card_id": outcome.card_id, "clarification_failures": 0}
    if outcome.card_id in eligible:
        update.update(await _check_active_and_eligibility(state, config, outcome.card_id))
        return update

    # Named by the customer but not replaceable: by status/origin, block it or a person.
    chosen = next(card for card in cards if card.card_id == outcome.card_id)
    kind = next_step_offer_kind(
        policy, status=chosen.status, origin_kind=origins.get(chosen.card_id, "none")
    )
    if kind == "human":
        update.update(offer("human", language, chosen.last4))
        update["pending"] = None
        return update
    update["pending"] = OFFER_BLOCK_PAUSE
    update["segments"] = [get_template("replacement_needs_block", language)]
    return update


async def _resume_offer(state: GraphState, config: RunnableConfig) -> dict[str, Any]:
    """The affirm/deny to `card_block`'s or `card_unlock`'s own offer (D11,
    D12): affirm continues with the card already selected there; deny
    declines without touching whatever write already happened."""
    language = state["language"]
    outcome = decision(state)
    card_id = state.get("selected_card_id")
    if outcome == "confirm" and card_id is not None:
        return await _check_active_and_eligibility(state, config, card_id)
    declined = closing(language)
    declined["segments"] = [get_template("replacement_declined", language), *declined["segments"]]
    return {**declined, **mark_segment("cancelled")}


async def _check_active_and_eligibility(
    state: GraphState, config: RunnableConfig, card_id: str
) -> dict[str, Any]:
    """The `customer_not_active` refusal first (D10), then the eligibility
    gate: `customer_block`, or a card already past its expiry (D13). Shared
    by a fresh card selection and the offer's own affirm, which both
    continue from "a card is selected" the same way."""
    bank_tools: BankReadTools = config["configurable"]["bank_tools"]
    bank_write_tools: ConfirmedWriteTools = config["configurable"]["bank_write_tools"]
    language = state["language"]
    country = state["country"]
    escalation = load_escalation_policy()

    try:
        profile = await bank_tools.get_profile()
    except ToolUnavailable:
        return {"escalation_reason": "tool_failure"}

    not_active = escalation.customer_not_active
    if (
        profile.customer_status in not_active.statuses
        and "order_replacement" not in not_active.allowed
    ):
        return handoff(
            rule_queue(escalation, "customer_not_active"), "customer_not_active", language
        )

    try:
        origin = await bank_write_tools.get_block_origin(card_id, "replacement_request")
        details = await bank_tools.get_card_details(card_id)
    except ToolUnavailable:
        return {"escalation_reason": "tool_failure"}

    expired = details.expiration_date is not None and details.expiration_date < local_today(country)
    if origin.kind != "customer_block" and not expired:
        return {
            "pending": None,
            "segments": [get_template("replacement_not_eligible", language)],
            **mark_segment("abstained"),
        }

    address_masked = f"•••, {profile.city}" if profile.city else "•••"
    text = fill(get_template("address_confirm", language), address_masked=address_masked)
    return {
        "pending": {
            "flow": "replacement",
            "node": "address_confirm",
            "awaiting_slot": "address_confirm",
        },
        "segments": [text],
    }


async def _resume_address_confirm(state: GraphState, config: RunnableConfig) -> dict[str, Any]:
    """The "send it to the address on file?" question (D13): affirm plans
    with `"on_file"` right away; deny needs step-up before a new address can
    be planned, unless it is already valid this session (D1, D2)."""
    language = state["language"]
    bank_write_tools: ConfirmedWriteTools = config["configurable"]["bank_write_tools"]
    outcome = decision(state)
    card_id = state.get("selected_card_id")
    if card_id is None:
        return {
            "pending": None,
            "segments": [get_template("nothing_pending", language)],
            **mark_segment("cancelled"),
        }
    if outcome == "confirm":
        return await _start_replacement_plan(state, config, card_id, "on_file")
    if outcome != "cancel":
        return {"segments": [get_template("nothing_pending", language)]}
    if await bank_write_tools.is_step_up_valid():
        return _ask_address(language)
    return otp_pause("replacement", "otp", "cards.order_replacement", language)


async def _resume_otp(state: GraphState, config: RunnableConfig) -> dict[str, Any]:
    """The step-up resume (D1): reached only through `resume="step_up"`."""
    bank_write_tools: ConfirmedWriteTools = config["configurable"]["bank_write_tools"]
    language = state["language"]
    card_id = state.get("selected_card_id")
    if card_id is None:
        return {
            "pending": None,
            "segments": [get_template("nothing_pending", language)],
            **mark_segment("cancelled"),
        }
    if await bank_write_tools.is_step_up_valid():
        return _ask_address(language)
    # Still invalid: pause again, nothing issued (D1).
    return otp_pause("replacement", "otp", "cards.order_replacement", language)


def _ask_address(language: Language) -> dict[str, Any]:
    return {
        "pending": {"flow": "replacement", "node": "address", "awaiting_slot": "address"},
        "segments": [get_template("address_ask", language)],
    }


async def _resume_address(state: GraphState, config: RunnableConfig) -> dict[str, Any]:
    """The address turn (D4): no `understand` ran this turn, so `user_text`
    is the raw address. `vault.put_address` is the only place it is ever
    read; only its opaque token continues into the plan (R5)."""
    language = state["language"]
    vault: AddressVault = config["configurable"]["vault"]
    card_id = state.get("selected_card_id")
    if card_id is None:
        return {
            "pending": None,
            "segments": [get_template("nothing_pending", language)],
            **mark_segment("cancelled"),
        }
    address_ref = vault.put_address(state["user_text"])
    return await _start_replacement_plan(state, config, card_id, address_ref)


async def _start_replacement_plan(
    state: GraphState, config: RunnableConfig, card_id: str, address_ref: str
) -> dict[str, Any]:
    """Issue the plan and remember `address_ref` in `state["slots"]` (a plain
    `NLUSlots(pending_answer=...)`, no reducer, last write wins) so the
    "confirm" resume -- whose own NLU turn only ever carries affirm/deny --
    still knows which address to pass `order_replacement` (D13, same
    pattern `card_block` uses for `block_kind`)."""
    bank_tools: BankReadTools = config["configurable"]["bank_tools"]
    language = state["language"]
    details = await bank_tools.get_card_details(card_id)

    view_facts = [Fact(key="card_mask", value=mask_card(details.last4), source=details.source)]
    confirm_values = {
        "action": _REPLACEMENT_ACTION_LABEL[language],
        "effect": _REPLACEMENT_EFFECT_LABEL[language],
        "card_last4": details.last4,
    }
    text = fill(get_template("action_confirm", language), **dict(confirm_values))
    update = await start_plan(
        state,
        config,
        flow="replacement",
        steps=[
            StepSpec(
                tool="cards.order_replacement",
                args={"card_id": details.card_id, "address_ref": address_ref},
                summary_key="order_replacement",
                view_facts=view_facts,
            )
        ],
        text=text,
        intent="replacement_request",
    )
    update["slots"] = NLUSlots(pending_answer=address_ref)
    return update


async def _resume_confirm(state: GraphState, config: RunnableConfig) -> dict[str, Any]:
    """The plan's confirm/cancel decision (D14): the write's `tracking_id`
    fills `action_done`'s `{reference}`, and `_REPLACEMENT_STATE_LABEL` fills
    its `{result}` the same way `card_block`/`card_unlock` fill
    `action_done_noref`'s (D17; T13 repair -- `{result}` was left unfilled)."""
    language = state["language"]
    outcome = decision(state)
    if outcome == "cancel":
        return await cancel(state, config)
    if outcome != "confirm":
        # `"stale"` or `None`: nothing this turn matches the open plan.
        return {"segments": [get_template("nothing_pending", language)]}

    card_id = state.get("selected_card_id")
    slots = state.get("slots")
    address_ref = slots.pending_answer if slots is not None else None
    token_id = state.get("confirmation_token_id")
    if card_id is None or address_ref is None or token_id is None:
        return {
            "pending": None,
            "confirmation_token_id": None,
            "segments": [get_template("nothing_pending", language)],
            **mark_segment("cancelled"),
        }

    bank_tools: BankReadTools = config["configurable"]["bank_tools"]
    bank_write_tools: ConfirmedWriteTools = config["configurable"]["bank_write_tools"]
    details = await bank_tools.get_card_details(card_id)

    async def call(
        card_id: str = card_id, address_ref: str = address_ref, token_id: str = token_id
    ) -> ActionResult:
        return await bank_write_tools.order_replacement(card_id, address_ref, token_id)

    update = await execute(
        state,
        config,
        call,
        done_template="action_done",
        done_values=lambda result: {
            "result": _REPLACEMENT_STATE_LABEL[language],
            "reference": result.tracking_id or "",
        },
        card_last4=details.last4,
    )
    return with_closing(state, update)
