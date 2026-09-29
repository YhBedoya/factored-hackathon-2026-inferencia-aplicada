"""Runs one turn against a hosted graph and publishes its events (D14).

`start_turn` is the API's one entry point: it takes the turn lock first (a
`SET turn:<conversation_id> <turn_id> NX EX 120`, so two concurrent posts to
the same conversation can't both run), persists the customer's message (only
when this is a typed turn, D6), then schedules the turn itself as an
`asyncio.Task` on `host.tasks` and returns right away with the `turn_id` --
`POST /messages`/`POST /confirmations/{token_id}` both answer `202` without
waiting for the graph to finish. Exactly one of `text`, `resume`,
`confirmation` or `selection` is set on any one call (D6, D7): a typed turn,
a step-up resume, a button confirm/cancel, or a transaction pick.
`checkpointed_confirmation_token` is the route's second D7 gate for a
confirmation -- the same `graph.aget_state(...).values.get(
"confirmation_token_id")` read the sandbox's `/confirm` already does --
and `checkpointed_dispute` is the analogous read for a pick (`pending` +
`dispute`).

The turn task builds its `ToolContext`, its one turn-bound `AuditRecorder`
and its read/write tools only through `registry` (R1, D13, D17): nothing
here ever reads `customer_id` off anything but the route's `Session`. The
same recorder that `RecordingBankTools` and `ConfirmedWriteTools` audit
their tool calls through also gets this module's own turn-level events:
`nlu_result` (from `understand`'s update), `rule_hit` for any
`escalation_reason` a flow sets this turn, and `reply_sent` just before the
bot's reply is published (D14). A recording failure at this level is logged
`audit.write_failed` and never fails the turn (D15) -- only a failed
`tool_call` audit inside a read or write blocks that call itself. It
mirrors `graph.run_turn`'s astream loop and debug assembly (not import it:
`run_turn` drives one call and returns, this drives one call and publishes
each step as it happens), then
publishes the bot's `ui`/`message`/`debug`/`done` events in order and
persists the bot reply. On any exception it logs `turn.failed` -- fields
only, no user text and no PII -- and publishes `error`/`done` instead.

The lock is released in `finally` only if it still holds this turn's own
`turn_id`: a Lua script reads and compares before it deletes, so a lock this
turn's own TTL already dropped (and a later turn already re-acquired) is
never deleted out from under that later turn.
"""

import asyncio
from typing import Literal
from uuid import UUID, uuid4

import structlog
from langchain_core.runnables import RunnableConfig
from pydantic import JsonValue

from app.core import events
from app.core.config import get_settings
from app.core.redis import get_redis
from app.domains.audit.schemas import AuditType
from app.domains.conversation import store
from app.domains.conversation.graph import ConfirmationDecision, DebugInfo, TxSelection
from app.domains.conversation.hosting import TurnHost
from app.domains.conversation.schemas import NLUResult, NLUSlots
from app.domains.conversation.state import DisputeState, Pending
from app.domains.conversation.tools import registry
from app.domains.conversation.tools.handoff import ServiceHandoffTools
from app.domains.conversation.ui import UIEvent
from app.domains.identity.models import Session
from app.domains.safety.vault import InMemoryAddressVault

__all__ = [
    "TurnInProgress",
    "checkpointed_confirmation_token",
    "checkpointed_dispute",
    "start_turn",
]

_logger = structlog.get_logger()

_LOCK_TTL_SECONDS = 120
# Mirrors `graph._BRANCH_NODES`, not imported (same "mirror, not import"
# convention `registry.RecordingBankTools` set for the sandbox's recorder):
# this module's job is to drive a hosted graph, not to reach into another
# module's private constant.
_BRANCH_NODES = (
    "card_info",
    "card_block",
    "card_unlock",
    "replacement",
    "unrecognized_charge",
    "unsupported",
    "fallback",
    "smalltalk",
    "abstain",
    "handoff",
)

_RELEASE_LOCK_SCRIPT = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
end
return 0
"""


class TurnInProgress(Exception):
    """`start_turn` raises this when the conversation's turn lock is already
    held. Nothing is persisted before this is raised (D14).
    """


async def start_turn(
    host: TurnHost,
    *,
    session: Session,
    conversation_id: UUID,
    trace_id: str,
    text: str | None = None,
    resume: Literal["step_up"] | None = None,
    confirmation: ConfirmationDecision | None = None,
    selection: TxSelection | None = None,
) -> UUID:
    """Take the turn lock, persist the customer message (only when `text` is
    set, D6), and schedule the turn task. Exactly one of `text`, `resume`,
    `confirmation` or `selection` must be set -- `ValueError` otherwise.
    `selection` (D4-B D7) is never persisted as a message, same as `resume`
    and `confirmation`: the route's own D7 gate is the injection guard, not
    this function. Raises `TurnInProgress` (nothing persisted) if the lock
    is already held.
    """
    if sum(value is not None for value in (text, resume, confirmation, selection)) != 1:
        raise ValueError("start_turn takes exactly one of text, resume, confirmation or selection")

    turn_id = uuid4()
    lock_key = f"turn:{conversation_id}"
    acquired = await get_redis().set(lock_key, str(turn_id), nx=True, ex=_LOCK_TTL_SECONDS)
    if not acquired:
        raise TurnInProgress(f"a turn is already running for conversation {conversation_id}")

    if text is not None:
        await store.add_message(conversation_id, turn_id, role="customer", content=text)

    task = asyncio.create_task(
        _run_turn(
            host,
            session=session,
            conversation_id=conversation_id,
            turn_id=turn_id,
            text=text,
            resume=resume,
            confirmation=confirmation,
            selection=selection,
            trace_id=trace_id,
        )
    )
    host.tasks.add(task)
    task.add_done_callback(host.tasks.discard)
    return turn_id


async def checkpointed_confirmation_token(host: TurnHost, conversation_id: UUID) -> str | None:
    """The `confirmation_token_id` this conversation's plan last checkpointed
    (D7's second gate, on top of `RedisConfirmationStore.is_open`): the same
    `graph.aget_state(...).values.get("confirmation_token_id")` read the
    sandbox's `/confirm` command already does. `None` on a conversation with
    no checkpoint yet or nothing pending.
    """
    state = await host.graph.aget_state({"configurable": {"thread_id": str(conversation_id)}})
    return state.values.get("confirmation_token_id")


async def checkpointed_dispute(
    host: TurnHost, conversation_id: UUID
) -> tuple[Pending | None, DisputeState | None]:
    """This conversation's last-checkpointed `pending` and `dispute` (D4-B
    D7's route gate): the same read `checkpointed_confirmation_token` does,
    for the pick's own two fields -- "is a transaction list actually open"
    and "what ids did it offer". `(None, None)` on a conversation with no
    checkpoint yet.
    """
    state = await host.graph.aget_state({"configurable": {"thread_id": str(conversation_id)}})
    return state.values.get("pending"), state.values.get("dispute")


async def _run_turn(
    host: TurnHost,
    *,
    session: Session,
    conversation_id: UUID,
    turn_id: UUID,
    text: str | None,
    resume: Literal["step_up"] | None,
    confirmation: ConfirmationDecision | None,
    selection: TxSelection | None,
    trace_id: str,
) -> None:
    lock_key = f"turn:{conversation_id}"
    try:
        ctx = registry.build_tool_context(session, conversation_id, trace_id)
        audit = registry.audit_recorder_for(ctx, turn_id)
        tools, write_tools = registry.turn_tools(ctx, session, audit)

        async def _record(event_type: AuditType, payload: dict[str, JsonValue]) -> None:
            """Best effort (D15): a runner-level audit event's recording
            failure is logged and never fails the turn -- only a failed
            `tool_call` audit inside a read or write blocks that call itself
            (`registry.RecordingBankTools`, `ConfirmedWriteTools`)."""
            try:
                await audit.record(event_type, payload)
            except Exception:
                _logger.warning(
                    "audit.write_failed",
                    conversation_id=str(conversation_id),
                    turn_id=str(turn_id),
                    trace_id=trace_id,
                    type=event_type,
                )

        config: RunnableConfig = {
            "configurable": {
                "thread_id": str(conversation_id),
                "session": ctx,
                "bank_tools": tools,
                "llm": host.llm,
                "bank_write_tools": write_tools,
                "vault": InMemoryAddressVault(),
                "handoff_tools": ServiceHandoffTools(ctx),
                "audit": audit,
            }
        }

        route_taken: str | None = None
        nlu: NLUResult | None = None
        language: Literal["es", "pt"] = "es"
        reply = ""
        ui: list[UIEvent] = []
        handed_off = False

        async for update in host.graph.astream(
            {
                "user_text": text or "",
                "confirmation": confirmation,
                "resume": resume,
                "selection": selection,
            },
            config=config,
            stream_mode="updates",
        ):
            for node_name, values in update.items():
                await events.publish(conversation_id, "status", {"step": node_name})
                if node_name == "relay_to_agent":
                    # Human mode (D13): echo the typed text for the agent and
                    # stop. Checked before the `None` guard because this node
                    # returns an empty update. The customer message was
                    # persisted by `start_turn`.
                    await events.publish(
                        conversation_id, "message", {"role": "customer", "text": text or ""}
                    )
                    await events.publish(conversation_id, "done", {"turn_id": str(turn_id)})
                    return
                # A node whose returned update is empty (e.g. `next_intent`
                # with nothing left to pop) streams as `None`, not `{}`.
                if values is None:
                    continue
                if node_name == "handoff" and values.get("handoff_id") is not None:
                    handed_off = True
                if node_name == "understand":
                    nlu = values.get("nlu")
                    language = values.get("language", language)
                    if nlu is not None:
                        await _record(
                            "nlu_result",
                            {
                                "language": language,
                                "status": nlu.status,
                                "intents": [intent for intent in nlu.intents],
                            },
                        )
                elif route_taken is None and node_name in _BRANCH_NODES:
                    route_taken = node_name
                reply_value = values.get("reply")
                if reply_value is not None:
                    reply = reply_value
                ui_value = values.get("ui")
                if ui_value is not None:
                    ui = ui_value
                escalation_reason = values.get("escalation_reason")
                if escalation_reason is not None:
                    await _record("rule_hit", {"rule_id": escalation_reason})

        for event in ui:
            await events.publish(conversation_id, "ui", event.model_dump(mode="json"))
        if handed_off:
            await events.publish(
                conversation_id, "mode", {"mode": "human", "agent_display_name": None}
            )

        ui_payload = [event.model_dump(mode="json") for event in ui] if ui else None
        await store.add_message(
            conversation_id, turn_id, role="bot", content=reply, ui_payload=ui_payload
        )
        await _record(
            "reply_sent",
            {
                "route": route_taken or "fallback",
                "ui_kinds": [event.kind for event in ui],
                "length": len(reply),
            },
        )
        await events.publish(
            conversation_id, "message", {"role": "bot", "text": reply, "sources": []}
        )
        if any(event.kind == "conversation_closed" for event in ui):
            await store.close_conversation(conversation_id)

        if get_settings().app_env != "prod":
            final_state = await host.graph.aget_state(config)
            pending = final_state.values.get("pending")
            debug = DebugInfo(
                language=language,
                status=nlu.status if nlu is not None else None,
                intents=nlu.intents if nlu is not None else [],
                slots=nlu.slots if nlu is not None else NLUSlots(),
                route=route_taken or "fallback",
                tools_called=tools.calls,
                pending=f"{pending['flow']}.{pending['awaiting_slot']}" if pending else None,
                ui=[event.kind for event in ui],
            )
            await events.publish(conversation_id, "debug", debug.model_dump(mode="json"))

        await events.publish(conversation_id, "done", {"turn_id": str(turn_id)})
    except Exception as exc:
        # No user text and no PII: only ids and the exception's class name.
        _logger.warning(
            "turn.failed",
            conversation_id=str(conversation_id),
            trace_id=trace_id,
            turn_id=str(turn_id),
            error_type=type(exc).__name__,
        )
        await events.publish(conversation_id, "error", {"code": "turn_failed"})
        await events.publish(conversation_id, "done", {"turn_id": str(turn_id)})
    finally:
        await get_redis().eval(_RELEASE_LOCK_SCRIPT, 1, lock_key, str(turn_id))
