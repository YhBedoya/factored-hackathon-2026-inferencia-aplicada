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
imports an LLM client (R6).
"""

from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

from langchain_core.runnables import RunnableConfig

from app.core.actions import ActionResult
from app.core.errors import ToolUnavailable
from app.domains.conversation.fact_values import record
from app.domains.conversation.flows.actions import (
    OFFER_BLOCK_PAUSE,
    StepSpec,
    cancel,
    closing,
    decision,
    execute,
    execute_plan,
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
from app.domains.conversation.templates import Language, TemplateKind, get_template
from app.domains.conversation.tools import BankReadTools
from app.domains.conversation.tools.executor import ConfirmedWriteTools
from app.domains.localization import local_today, mask_card
from app.domains.localization.format import format_time
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
    update = await _dispatch(state, config)
    # Every end of the flow clears the offered/selected list (D36): a handoff, a
    # not-eligible refusal, a decline, a cancel and a done all leave no pause in
    # this flow. Set once here so no ending can forget it.
    pending = update.get("pending", state.get("pending"))
    ended = "escalation_reason" in update or (
        "pending" in update and (pending is None or pending["flow"] != "replacement")
    )
    if ended:
        update.setdefault("replacement_card_ids", None)
    return update


async def _dispatch(state: GraphState, config: RunnableConfig) -> dict[str, Any]:
    pending = state.get("pending")
    node = pending["node"] if pending is not None else None

    if node == "cards":
        return await _resume_cards(state, config)
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


async def _resume_cards(state: GraphState, config: RunnableConfig) -> dict[str, Any]:
    """The multi-select picker's answer (D32, D34-D36): the ids the customer
    chose among those offered, or `[]` for "No, gracias" / an empty submit."""
    language = state["language"]
    selection = state.get("card_selection")
    offered = state.get("replacement_card_ids") or []
    if selection is None or not set(selection.card_ids) <= set(offered):
        # A typed turn that got past the gate, or ids that were never offered (the
        # second gate): change nothing and show the stored offer and picker again.
        return _replay_offer(state)

    if not selection.card_ids:
        declined = closing(language)
        declined["segments"] = [
            get_template("replacement_declined_multi", language),
            *declined["segments"],
        ]
        return {**declined, "replacement_card_ids": None, **mark_segment("cancelled")}

    bank_tools: BankReadTools = config["configurable"]["bank_tools"]
    try:
        profile = await bank_tools.get_profile()
    except ToolUnavailable:
        return {"escalation_reason": "tool_failure"}
    refusal = _not_active_handoff(profile.customer_status, language)
    if refusal is not None:
        return {**refusal, "replacement_card_ids": None}

    chosen = [card_id for card_id in offered if card_id in selection.card_ids]
    segments: list[str] = []
    eligible_ids: list[str] = []
    try:
        for card_id in chosen:
            ok, last4 = await _card_eligible(state, config, card_id)
            if ok:
                eligible_ids.append(card_id)
            else:
                segments.append(
                    fill(
                        get_template("replacement_card_not_eligible", language),
                        card_mask=mask_card(last4),
                    )
                )
    except ToolUnavailable:
        return {"escalation_reason": "tool_failure"}

    if not eligible_ids:
        segments.append(get_template("replacement_not_eligible", language))
        return {
            "pending": None,
            "replacement_card_ids": None,
            "segments": segments,
            **mark_segment("abstained"),
        }
    kind: TemplateKind = "address_confirm" if len(eligible_ids) == 1 else "address_confirm_multi"
    update = _address_confirm_update(profile.city, language, kind)
    update["segments"] = [*segments, *update["segments"]]
    update["replacement_card_ids"] = eligible_ids
    update["selected_card_id"] = eligible_ids[0]
    return update


def _replay_offer(state: GraphState) -> dict[str, Any]:
    """Re-send the stored offer and picker: no LLM, no write, no counter change,
    pause and offered ids kept (D33, open item C)."""
    stored = state.get("open_question")
    update: dict[str, Any] = {"non_answer_counted": True}
    if stored is not None:
        # D16: the replayed sentence is grounded once already; recording it keeps
        # `reply_sent.fact_values` covering the whole reply.
        record(stored["text"])
        update["segments"] = [stored["text"]]
        update["ui"] = list(stored["ui"])
        update["asked_ui"] = list(stored["ui"])
    return update


def _not_active_handoff(customer_status: str, language: Language) -> dict[str, Any] | None:
    """The `customer_not_active` refusal (D10): a check on the customer, not the card."""
    escalation = load_escalation_policy()
    not_active = escalation.customer_not_active
    if customer_status in not_active.statuses and "order_replacement" not in not_active.allowed:
        return handoff(
            rule_queue(escalation, "customer_not_active"), "customer_not_active", language
        )
    return None


async def _card_eligible(
    state: GraphState, config: RunnableConfig, card_id: str
) -> tuple[bool, str]:
    """Whether one card can be replaced -- block origin `customer_block`, or the
    card already past its expiry (D13) -- and its last4 for the refusal mask."""
    bank_tools: BankReadTools = config["configurable"]["bank_tools"]
    bank_write_tools: ConfirmedWriteTools = config["configurable"]["bank_write_tools"]
    origin = await bank_write_tools.get_block_origin(card_id, "replacement_request")
    details = await bank_tools.get_card_details(card_id)
    expired = details.expiration_date is not None and details.expiration_date < local_today(
        state["country"]
    )
    return origin.kind == "customer_block" or expired, details.last4


def _address_confirm_update(
    city: str | None, language: Language, kind: TemplateKind
) -> dict[str, Any]:
    address_masked = f"•••, {city}" if city else "•••"
    return {
        "pending": {
            "flow": "replacement",
            "node": "address_confirm",
            "awaiting_slot": "address_confirm",
        },
        "segments": [fill(get_template(kind, language), address_masked=address_masked)],
    }


async def _check_active_and_eligibility(
    state: GraphState, config: RunnableConfig, card_id: str
) -> dict[str, Any]:
    """The `customer_not_active` refusal first (D10), then the eligibility
    gate: `customer_block`, or a card already past its expiry (D13). Shared
    by a fresh card selection and the offer's own affirm, which both
    continue from "a card is selected" the same way."""
    bank_tools: BankReadTools = config["configurable"]["bank_tools"]
    language = state["language"]

    try:
        profile = await bank_tools.get_profile()
    except ToolUnavailable:
        return {"escalation_reason": "tool_failure"}

    refusal = _not_active_handoff(profile.customer_status, language)
    if refusal is not None:
        return refusal

    try:
        ok, _ = await _card_eligible(state, config, card_id)
    except ToolUnavailable:
        return {"escalation_reason": "tool_failure"}
    if not ok:
        return {
            "pending": None,
            "segments": [get_template("replacement_not_eligible", language)],
            **mark_segment("abstained"),
        }

    update = _address_confirm_update(profile.city, language, "address_confirm")
    # Open item E: a one-card pause leaves no stale offered list behind.
    update["replacement_card_ids"] = None
    return update


async def _resume_address_confirm(state: GraphState, config: RunnableConfig) -> dict[str, Any]:
    """The "send it to the address on file?" question (D13): affirm plans
    with `"on_file"` right away; deny needs step-up before a new address can
    be planned, unless it is already valid this session (D1, D2)."""
    language = state["language"]
    bank_write_tools: ConfirmedWriteTools = config["configurable"]["bank_write_tools"]
    outcome = decision(state)
    card_ids = _plan_card_ids(state)
    if not card_ids:
        return {
            "pending": None,
            "segments": [get_template("nothing_pending", language)],
            **mark_segment("cancelled"),
        }
    if outcome == "confirm":
        return await _start_replacement_plan(state, config, card_ids, "on_file")
    if outcome != "cancel":
        return {"segments": [get_template("nothing_pending", language)]}
    if await bank_write_tools.is_step_up_valid():
        return _ask_address(language, len(card_ids))
    return otp_pause("replacement", "otp", "cards.order_replacement", language)


async def _resume_otp(state: GraphState, config: RunnableConfig) -> dict[str, Any]:
    """The step-up resume (D1): reached only through `resume="step_up"`."""
    bank_write_tools: ConfirmedWriteTools = config["configurable"]["bank_write_tools"]
    language = state["language"]
    card_ids = _plan_card_ids(state)
    if not card_ids:
        return {
            "pending": None,
            "segments": [get_template("nothing_pending", language)],
            **mark_segment("cancelled"),
        }
    if await bank_write_tools.is_step_up_valid():
        return _ask_address(language, len(card_ids))
    # Still invalid: pause again, nothing issued (D1).
    return otp_pause("replacement", "otp", "cards.order_replacement", language)


def _plan_card_ids(state: GraphState) -> list[str]:
    """The cards this replacement covers: the selected list, else the one card."""
    ids = state.get("replacement_card_ids")
    if ids:
        return list(ids)
    selected = state.get("selected_card_id")
    return [selected] if selected is not None else []


def _ask_address(language: Language, count: int = 1) -> dict[str, Any]:
    kind: TemplateKind = "address_ask" if count == 1 else "address_ask_multi"
    return {
        "pending": {"flow": "replacement", "node": "address", "awaiting_slot": "address"},
        "segments": [get_template(kind, language)],
    }


async def _resume_address(state: GraphState, config: RunnableConfig) -> dict[str, Any]:
    """The address turn (D4): no `understand` ran this turn, so `user_text`
    is the raw address. `vault.put_address` is the only place it is ever
    read; only its opaque token continues into the plan (R5)."""
    language = state["language"]
    vault: AddressVault = config["configurable"]["vault"]
    card_ids = _plan_card_ids(state)
    if not card_ids:
        return {
            "pending": None,
            "segments": [get_template("nothing_pending", language)],
            **mark_segment("cancelled"),
        }
    address_ref = vault.put_address(state["user_text"])
    return await _start_replacement_plan(state, config, card_ids, address_ref)


async def _start_replacement_plan(
    state: GraphState, config: RunnableConfig, card_ids: list[str], address_ref: str
) -> dict[str, Any]:
    """Issue the plan and remember `address_ref` in `state["slots"]` (a plain
    `NLUSlots(pending_answer=...)`, no reducer, last write wins) so the
    "confirm" resume -- whose own NLU turn only ever carries affirm/deny --
    still knows which address to pass `order_replacement` (D13, same
    pattern `card_block` uses for `block_kind`). Several cards are one plan
    with one step each, under one token (D34)."""
    bank_tools: BankReadTools = config["configurable"]["bank_tools"]
    language = state["language"]
    steps: list[StepSpec] = []
    last4 = ""
    for card_id in card_ids:
        details = await bank_tools.get_card_details(card_id)
        last4 = details.last4
        steps.append(
            StepSpec(
                tool="cards.order_replacement",
                args={"card_id": details.card_id, "address_ref": address_ref},
                summary_key="order_replacement",
                view_facts=[
                    Fact(key="card_mask", value=mask_card(details.last4), source=details.source)
                ],
            )
        )

    if len(card_ids) == 1:
        text = fill(
            get_template("action_confirm", language),
            action=_REPLACEMENT_ACTION_LABEL[language],
            effect=_REPLACEMENT_EFFECT_LABEL[language],
            card_last4=last4,
        )
    else:
        text = get_template("action_confirm_multi", language)
    update = await start_plan(
        state, config, flow="replacement", steps=steps, text=text, intent="replacement_request"
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

    card_ids = _plan_card_ids(state)
    slots = state.get("slots")
    address_ref = slots.pending_answer if slots is not None else None
    token_id = state.get("confirmation_token_id")
    if not card_ids or address_ref is None or token_id is None:
        return {
            "pending": None,
            "confirmation_token_id": None,
            "segments": [get_template("nothing_pending", language)],
            **mark_segment("cancelled"),
        }

    bank_tools: BankReadTools = config["configurable"]["bank_tools"]
    bank_write_tools: ConfirmedWriteTools = config["configurable"]["bank_write_tools"]
    if len(card_ids) > 1:
        return await _execute_many(
            state, config, card_ids, address_ref=address_ref, token_id=token_id
        )

    card_id = card_ids[0]
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


async def _execute_many(
    state: GraphState,
    config: RunnableConfig,
    card_ids: list[str],
    *,
    address_ref: str,
    token_id: str,
) -> dict[str, Any]:
    """Run the N confirmed steps in order, one read-back each (R3, D34). Any
    failed or unverified step stops the plan and hands off; "done" is said only
    when every step verified, once per card with its own tracking id."""
    bank_tools: BankReadTools = config["configurable"]["bank_tools"]
    bank_write_tools: ConfirmedWriteTools = config["configurable"]["bank_write_tools"]
    language = state["language"]
    country = state["country"]

    def make_call(card_id: str) -> Callable[[], Awaitable[ActionResult]]:
        async def call() -> ActionResult:
            return await bank_write_tools.order_replacement(card_id, address_ref, token_id)

        return call

    outcome = await execute_plan(state, config, [make_call(card_id) for card_id in card_ids])
    if isinstance(outcome, dict):
        return {**outcome, "replacement_card_ids": None}

    segments: list[str] = []
    for card_id, result in zip(card_ids, outcome, strict=True):
        details = await bank_tools.get_card_details(card_id)
        at = result.readback.get("at")
        segments.append(
            fill(
                get_template("action_done", language),
                result=_REPLACEMENT_STATE_LABEL[language],
                reference=result.tracking_id or "",
                card_last4=details.last4,
                time=format_time(at, country) if isinstance(at, datetime) else "",
            )
        )
    update = {
        "actions": outcome,
        "pending": None,
        "confirmation_token_id": None,
        "replacement_card_ids": None,
        "segments": segments,
    }
    return with_closing(state, update)
