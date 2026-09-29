"""Shared helpers every confirmed-write flow needs (D11-D13, D2-K's contracts).

`card_block` (this card) and the later `card_unlock`/`replacement` flows all
run the same shape: fill a fixed template, issue a one-step plan and pause
for confirmation, read the button/NLU decision, cancel or execute, and on a
verified read-back fill the "done" template -- never anything else claiming
"listo" (R3). Lifting that shape here once means each flow module only
supplies its own tool call, template kinds and fill values.

This module never imports `app.core.llm` (R6): it reads write tools only
through `config["configurable"]["bank_write_tools"]` (a `ConfirmedWriteTools`,
D2-K D5), the one key the R6 scan guards, and never a raw `BankWriteTools`.
"""

from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime
from typing import Any

from langchain_core.runnables import RunnableConfig

from app.core.actions import ActionResult
from app.core.errors import ConfirmationRequired
from app.domains.conversation.graph import GraphState
from app.domains.conversation.schemas import Intent
from app.domains.conversation.state import Fact
from app.domains.conversation.templates import Language, TemplateKind, get_template
from app.domains.conversation.tools.executor import ConfirmedWriteTools
from app.domains.conversation.ui import (
    ConfirmEvent,
    ConfirmPayload,
    ConfirmStepView,
    OtpRequiredEvent,
    OtpRequiredPayload,
)
from app.domains.handoff.schemas import HandoffReason
from app.domains.localization.format import Queue, format_time
from app.domains.policy.confirmation import PlanStep, ToolArg
from app.domains.policy.escalation import load_escalation_policy, rule_queue

__all__ = [
    "DoneValues",
    "cancel",
    "decision",
    "execute",
    "fill",
    "handoff",
    "otp_pause",
    "start_plan",
]

DoneValues = Mapping[str, str] | Callable[[ActionResult], Mapping[str, str]]
"""`execute`'s `done_values`: a fixed mapping (lock/unlock/block, D17's
`action_done_noref`), or a function of the verified `ActionResult` (D13's
`replacement`, whose `{reference} = tracking_id` is only known after the
write returns)."""


def fill(template: str, **values: str) -> str:
    """Fill `{key}` placeholders with already-formatted values (R4).

    Plain `str.replace`, not `str.format`: a stray, unfilled `{other}` in the
    template is left untouched rather than raising `KeyError`.
    """
    text = template
    for key, value in values.items():
        text = text.replace(f"{{{key}}}", value)
    return text


async def start_plan(
    state: GraphState,
    config: RunnableConfig,
    *,
    flow: str,
    tool: str,
    args: Mapping[str, ToolArg],
    summary_key: str,
    view_facts: list[Fact],
    confirm_values: Mapping[str, str],
    intent: Intent,
) -> dict[str, Any]:
    """Issue a one-step plan and pause for the button/NLU confirmation (D11,
    D2-K D15). `confirm_values` fills `action_confirm`'s `{action}`/`{effect}`/
    `{card_last4}` placeholders; `view_facts` is what `ui.confirm` shows the
    customer before they decide (already formatted, R4). `intent` is the
    allowlist check `issue_plan` runs before the store is ever touched (D3).
    """
    bank_write_tools: ConfirmedWriteTools = config["configurable"]["bank_write_tools"]
    plan = await bank_write_tools.issue_plan([PlanStep(tool=tool, args=dict(args))], intent)
    language = state["language"]
    text = fill(get_template("action_confirm", language), **dict(confirm_values))
    return {
        "confirmation_token_id": plan.token_id,
        "pending": {"flow": flow, "node": "confirm", "awaiting_slot": "confirmation"},
        "ui": [
            ConfirmEvent(
                kind="confirm",
                payload=ConfirmPayload(
                    token_id=plan.token_id,
                    steps=[ConfirmStepView(tool=tool, summary_key=summary_key, facts=view_facts)],
                ),
            )
        ],
        "segments": [text],
    }


def decision(state: GraphState) -> str | None:
    """`"confirm"`, `"cancel"`, `"stale"` or `None` (D14).

    A button `confirmation` whose token doesn't match `confirmation_token_id`
    is stale (a leftover click on an old card, or a replayed request); it
    never executes anything. A typed turn has no `confirmation` at all, so
    the NLU affirm/deny intents decide instead.
    """
    confirmation = state.get("confirmation")
    if confirmation is not None:
        if confirmation.token_id != state.get("confirmation_token_id"):
            return "stale"
        return confirmation.decision
    nlu = state.get("nlu")
    if nlu is not None:
        if "affirm" in nlu.intents:
            return "confirm"
        if "deny" in nlu.intents:
            return "cancel"
    return None


async def cancel(state: GraphState, config: RunnableConfig) -> dict[str, Any]:
    """A typed "no" or `/cancel`: cancel the plan, say nothing happened (D14)."""
    bank_write_tools: ConfirmedWriteTools = config["configurable"]["bank_write_tools"]
    token_id = state.get("confirmation_token_id")
    if token_id is not None:
        await bank_write_tools.cancel_plan(token_id)
    return {
        "pending": None,
        "confirmation_token_id": None,
        "segments": [get_template("action_cancelled", state["language"])],
    }


async def execute(
    state: GraphState,
    config: RunnableConfig,
    call: Callable[[], Awaitable[ActionResult]],
    *,
    done_template: TemplateKind,
    done_values: DoneValues,
    card_last4: str,
) -> dict[str, Any]:
    """Run the confirmed write and report only a verified result (R3, D17).

    `call` is the caller's own zero-arg coroutine factory (already bound to
    the tool's args and the confirmation token), so this helper never has to
    know each write tool's own signature. A `ConfirmationRequired` (the
    token was reused, expired or belongs to someone else) cancels the plan
    the same as a typed "no"; any other exception, or a returned but
    unverified result, goes to the `action_unverified` handoff -- never a
    "listo" the customer didn't earn. `done_values` is a fixed mapping, or a
    function of the verified `ActionResult` for a value only the write
    itself produces (D13's `tracking_id`).
    """
    language = state["language"]
    country = state["country"]
    try:
        result = await call()
    except ConfirmationRequired:
        return await cancel(state, config)
    except Exception:
        return _action_unverified_handoff(language)

    if not result.verified:
        return _action_unverified_handoff(language)

    at = result.readback.get("at")
    time_text = format_time(at, country) if isinstance(at, datetime) else ""
    values = done_values(result) if callable(done_values) else done_values
    text = fill(
        get_template(done_template, language),
        **dict(values),
        card_last4=card_last4,
        time=time_text,
    )
    return {
        "actions": [result],
        "pending": None,
        "confirmation_token_id": None,
        "segments": [text],
    }


def _action_unverified_handoff(language: Language) -> dict[str, Any]:
    queue = rule_queue(load_escalation_policy(), "action_unverified")
    return handoff(queue, "action_unverified", language)


def handoff(queue: Queue, reason: HandoffReason, language: Language) -> dict[str, Any]:
    """Mark the turn for handoff (D4): the `handoff_summary`/`handoff` nodes
    write the packet and the customer's reply, so no segment is set here.
    `language` stays in the signature so callers are unchanged.
    """
    return {
        "escalation_reason": reason,
        "handoff_queue": queue,
        "pending": None,
        "confirmation_token_id": None,
    }


def otp_pause(flow: str, node: str, tool: str, language: Language) -> dict[str, Any]:
    """Pause before a plan can even be issued, waiting on step-up (D1, ADR-027)."""
    return {
        "pending": {"flow": flow, "node": node, "awaiting_slot": "otp"},
        "ui": [OtpRequiredEvent(kind="otp_required", payload=OtpRequiredPayload(tool=tool))],
        "segments": [get_template("otp_required", language)],
    }
