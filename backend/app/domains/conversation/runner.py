"""Runs one turn against a hosted graph and publishes its events (D14).

`start_turn` is the API's one entry point: it takes the turn lock first (a
`SET turn:<conversation_id> <turn_id> NX EX 120`, so two concurrent posts to
the same conversation can't both run), persists the customer's message, then
schedules the turn itself as an `asyncio.Task` on `host.tasks` and returns
right away with the `turn_id` -- `POST /messages` answers `202` without
waiting for the graph to finish.

The turn task builds its `ToolContext` and bank tools only through
`registry` (R1): nothing here ever reads `customer_id` off anything but the
route's `Session`. `bank_write_tools` is always `None` on the API path (D13)
-- there is no write path yet; a flow that finds it `None` must fall back
rather than claim anything is done. It mirrors `graph.run_turn`'s astream
loop and debug assembly (not import it: `run_turn` drives one call and
returns, this drives one call and publishes each step as it happens), then
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

from app.core import events
from app.core.config import get_settings
from app.core.redis import get_redis
from app.domains.conversation import store
from app.domains.conversation.graph import DebugInfo
from app.domains.conversation.hosting import TurnHost
from app.domains.conversation.schemas import NLUResult, NLUSlots
from app.domains.conversation.tools import registry
from app.domains.conversation.ui import UIEvent
from app.domains.identity.models import Session

__all__ = ["TurnInProgress", "start_turn"]

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
    "unsupported",
    "fallback",
    "smalltalk",
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
    text: str,
    trace_id: str,
) -> UUID:
    """Take the turn lock, persist the customer message, and schedule the
    turn task. Raises `TurnInProgress` (nothing persisted) if the lock is
    already held.
    """
    turn_id = uuid4()
    lock_key = f"turn:{conversation_id}"
    acquired = await get_redis().set(lock_key, str(turn_id), nx=True, ex=_LOCK_TTL_SECONDS)
    if not acquired:
        raise TurnInProgress(f"a turn is already running for conversation {conversation_id}")

    await store.add_message(conversation_id, turn_id, role="customer", content=text)

    task = asyncio.create_task(
        _run_turn(
            host,
            session=session,
            conversation_id=conversation_id,
            turn_id=turn_id,
            text=text,
            trace_id=trace_id,
        )
    )
    host.tasks.add(task)
    task.add_done_callback(host.tasks.discard)
    return turn_id


async def _run_turn(
    host: TurnHost,
    *,
    session: Session,
    conversation_id: UUID,
    turn_id: UUID,
    text: str,
    trace_id: str,
) -> None:
    lock_key = f"turn:{conversation_id}"
    try:
        ctx = registry.build_tool_context(session, conversation_id, trace_id)
        tools = registry.bank_tools_for(ctx)
        config: RunnableConfig = {
            "configurable": {
                "thread_id": str(conversation_id),
                "session": ctx,
                "bank_tools": tools,
                "llm": host.llm,
                "bank_write_tools": None,
            }
        }

        route_taken: str | None = None
        nlu: NLUResult | None = None
        language: Literal["es", "pt"] = "es"
        reply = ""
        ui: list[UIEvent] = []

        async for update in host.graph.astream(
            {"user_text": text, "confirmation": None, "resume": None},
            config=config,
            stream_mode="updates",
        ):
            for node_name, values in update.items():
                await events.publish(conversation_id, "status", {"step": node_name})
                # A node whose returned update is empty (e.g. `next_intent`
                # with nothing left to pop) streams as `None`, not `{}`.
                if values is None:
                    continue
                if node_name == "understand":
                    nlu = values.get("nlu")
                    language = values.get("language", language)
                elif route_taken is None and node_name in _BRANCH_NODES:
                    route_taken = node_name
                reply_value = values.get("reply")
                if reply_value is not None:
                    reply = reply_value
                ui_value = values.get("ui")
                if ui_value is not None:
                    ui = ui_value

        for event in ui:
            await events.publish(conversation_id, "ui", event.model_dump(mode="json"))

        ui_payload = [event.model_dump(mode="json") for event in ui] if ui else None
        await store.add_message(
            conversation_id, turn_id, role="bot", content=reply, ui_payload=ui_payload
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
