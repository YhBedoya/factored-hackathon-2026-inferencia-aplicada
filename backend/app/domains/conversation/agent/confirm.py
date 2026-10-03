"""The button node and the typed-turn code for an open agent plan (S1 D12-D17).

An agent plan is confirmed only by the card's buttons (D12): `agent_plan` runs on a
click, never on typed text. Acepto executes the stored steps through
`flows.actions.execute_plan` with no LLM call before the writes (D14); No acepto cancels
in code (D15). Either way the node hands the turn back to `agent` with
`agent_code_text` (the code-written result text) and `agent_plan_result` (what the agent's
turn event is built from), unless a step failed: then the handoff update goes out as a
flow's would, and Cardy never writes on that turn (D14).

This module never imports the LLM package (R6). It reads write tools only through
`config["configurable"]`, like `flows/actions.py`.
"""

from datetime import datetime
from typing import Any, Literal

from langchain_core.runnables import RunnableConfig

from app.core.actions import ActionResult
from app.domains.conversation.flows.actions import (
    OFFER_REPLACEMENT_PAUSE,
    decision,
    execute_plan,
    fill,
    handoff,
)
from app.domains.conversation.flows.card_block import _BLOCK_STATE_LABEL, _LOCK_STATE_LABEL
from app.domains.conversation.graph import GraphState
from app.domains.conversation.state import IntentSegment, SegmentStatus
from app.domains.conversation.templates import Language, get_template
from app.domains.conversation.tools import BankReadTools
from app.domains.conversation.tools.executor import ConfirmedWriteTools
from app.domains.conversation.ui import CardPickerEvent, CardPickerPayload, PickerOption
from app.domains.localization import kind_label, mask_card
from app.domains.localization.format import format_time
from app.domains.policy.escalation import rule_queue
from app.domains.policy.registry import get_policies

__all__ = ["agent_plan", "count_open_plan_turn", "replay_open_plan"]

CardKind = Literal["credit", "debit"]

# D17 (b): typed turns that end with the same plan open get the card twice; the third hands off.
_MAX_OPEN_PLAN_TURNS = 3

_CLEARED: dict[str, Any] = {
    "pending": None,
    "confirmation_token_id": None,
    "agent_plan_steps": None,
}


def _segment(status: SegmentStatus) -> list[IntentSegment]:
    # Lock and block are one request type in the catalog (`card_block`).
    return [{"intent": "card_block", "route": "card_block", "status": status}]


def replay_open_plan(state: GraphState, text: str | None = None) -> dict[str, Any]:
    """The stored card again, same token, no `issue_plan` call (D13). `text` is the
    sentence sent with it; the default is the `pending_reminder` template."""
    language = state.get("language", "es")
    segment = text if text is not None else get_template("pending_reminder", language)
    update: dict[str, Any] = {"segments": [segment]}
    stored = state.get("open_question")
    if stored is not None:
        update["ui"] = list(stored["ui"])
        update["asked_ui"] = list(stored["ui"])
    return update


async def count_open_plan_turn(
    state: GraphState, config: RunnableConfig, text: str | None = None
) -> dict[str, Any]:
    """D17 (b): a typed turn that ends with the same plan still open. The first two
    replay the card; the third cancels the plan and hands off `clarification_exhausted`."""
    count = state.get("non_answer_failures", 0) + 1
    if count < _MAX_OPEN_PLAN_TURNS:
        return {
            **replay_open_plan(state, text),
            "non_answer_failures": count,
            "non_answer_counted": True,
        }
    token_id = state.get("confirmation_token_id")
    write_tools: ConfirmedWriteTools = config["configurable"]["bank_write_tools"]
    if token_id is not None:
        await write_tools.cancel_plan(token_id)
    return {
        **handoff(
            rule_queue(get_policies().escalation, "clarification_exhausted"),
            "clarification_exhausted",
            state.get("language", "es"),
        ),
        "agent_plan_steps": None,
        "non_answer_failures": 0,
        "intent_segments": [{"intent": "card_block", "route": "handoff", "status": "handoff"}],
    }


async def agent_plan(state: GraphState, config: RunnableConfig) -> dict[str, Any]:
    """A button on an open agent plan (D12, D14, D15)."""
    language = state.get("language", "es")
    outcome = decision(state)
    steps = state.get("agent_plan_steps") or []
    if outcome == "cancel" and state.get("confirmation_token_id") is not None:
        return await _decline(state, config)
    if outcome != "confirm" or not steps:
        # A stale token (or a plan with nothing stored): nothing runs; the reminder and the
        # stored card go out again. The typed-turn count is kept, not reset (D17 b): only a
        # new plan resets it.
        return {**replay_open_plan(state), "non_answer_counted": True}
    return await _accept(state, config, language)


async def _decline(state: GraphState, config: RunnableConfig) -> dict[str, Any]:
    write_tools: ConfirmedWriteTools = config["configurable"]["bank_write_tools"]
    token_id = state.get("confirmation_token_id")
    assert token_id is not None
    await write_tools.cancel_plan(token_id)
    return {
        **_CLEARED,
        "agent_code_text": get_template("action_cancelled", state.get("language", "es")),
        "agent_plan_result": {"outcome": "declined", "steps": []},
        "intent_segments": _segment("cancelled"),
    }


async def _accept(state: GraphState, config: RunnableConfig, language: Language) -> dict[str, Any]:
    bank_tools: BankReadTools = config["configurable"]["bank_tools"]
    write_tools: ConfirmedWriteTools = config["configurable"]["bank_write_tools"]
    token_id = state.get("confirmation_token_id")
    steps = state.get("agent_plan_steps") or []
    assert token_id is not None

    last4: list[str] = []
    blocked: list[tuple[str, CardKind, str]] = []  # (card_id, kind, last4) of permanent blocks
    calls = []
    for step in steps:
        card_id = step["card_id"]
        details = await bank_tools.get_card_details(card_id)
        last4.append(details.last4)
        if step["action"] == "block":
            blocked.append((card_id, details.kind, details.last4))
        if step["action"] == "lock":

            async def call(card_id: str = card_id) -> ActionResult:
                return await write_tools.lock_card(card_id, token_id)

        else:

            async def call(card_id: str = card_id) -> ActionResult:
                # The reason is set by code, never by the model (D8).
                return await write_tools.block_card(card_id, "lost_or_stolen", token_id)

        calls.append(call)

    results = await execute_plan(state, config, calls)
    if isinstance(results, dict):
        # A failed or unverified step cancelled the plan: the flow's handoff update, as is.
        return {
            **results,
            **_CLEARED,
            "intent_segments": _segment("handoff"),
        }

    texts: list[str] = []
    for step, result, digits in zip(steps, results, last4, strict=True):
        label = (_LOCK_STATE_LABEL if step["action"] == "lock" else _BLOCK_STATE_LABEL)[language]
        at = result.readback.get("at")
        texts.append(
            fill(
                get_template("action_done_noref", language),
                result=label,
                card_last4=digits,
                time=format_time(at, state["country"]) if isinstance(at, datetime) else "",
            )
        )
    return {
        **_CLEARED,
        "actions": results,
        "agent_code_text": "\n\n".join(texts),
        "agent_plan_result": {
            "outcome": "confirmed",
            "steps": [{"action": s["action"], "card_id": s["card_id"]} for s in steps],
        },
        "intent_segments": _segment("resolved"),
        "agent_offer": _replacement_offer(blocked, language),
    }


def _replacement_offer(
    blocked: list[tuple[str, CardKind, str]], language: Language
) -> dict[str, Any] | None:
    """The replacement offer after a fully verified plan (D28-D30), written by code.

    Only permanent blocks get one: a lock is reversible. The agent node appends it after
    Cardy's reply; it never enters a loop message or tool result (R6).
    """
    if not blocked:
        return None
    if len(blocked) == 1:
        card_id, _, digits = blocked[0]
        return {
            "segment": fill(get_template("offer_replacement", language), card_last4=digits),
            "ui": None,
            "pending": OFFER_REPLACEMENT_PAUSE,
            "selected_card_id": card_id,
            # Open item E: the one-card offer is today's, so the multi field stays unset.
            "replacement_card_ids": None,
        }
    picker = CardPickerEvent(
        kind="card_picker",
        payload=CardPickerPayload(
            multi=True,
            options=[
                PickerOption(
                    card_id=card_id, label=f"{kind_label(kind, language)} {mask_card(digits)}"
                )
                for card_id, kind, digits in blocked
            ],
        ),
    )
    return {
        "segment": get_template("offer_replacement_multi", language),
        "ui": picker,
        "pending": {"flow": "replacement", "node": "cards", "awaiting_slot": "replacement_cards"},
        "selected_card_id": None,
        "replacement_card_ids": [card_id for card_id, _, _ in blocked],
    }
