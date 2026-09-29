"""Helpers for a human agent's takeover of a conversation (D13, D14, D16).

The staff routes call these; they never touch `app.handoffs` or
`app.conversations.mode` (the route's `handoff.service` call does that) and
they hold no bank tools. `return_to_bot` takes the same `turn:<id>` lock the
turn runner uses, so a customer turn can't race the checkpoint edit.
"""

from uuid import UUID, uuid4

from app.core import events
from app.core.redis import get_redis
from app.domains.conversation import store
from app.domains.conversation.hosting import TurnHost
from app.domains.conversation.templates import get_template
from app.domains.conversation.ui import MessagePayload, ModePayload
from app.domains.localization.format import Language

__all__ = ["TurnBusy", "publish_mode", "relay_agent_message", "return_to_bot"]

_LOCK_TTL_SECONDS = 120
# Same compare-and-delete as the runner's, so a lock that expired and was
# re-taken by a later turn is never deleted out from under it.
_RELEASE_LOCK_SCRIPT = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
end
return 0
"""


class TurnBusy(Exception):
    """The conversation's turn lock is held; the caller answers 409."""


async def publish_mode(conversation_id: UUID, mode: str, agent_display_name: str | None) -> None:
    """Publish a `mode` event on `conv:<id>`."""
    payload = ModePayload.model_validate({"mode": mode, "agent_display_name": agent_display_name})
    await events.publish(conversation_id, "mode", payload.model_dump(mode="json"))


async def relay_agent_message(conversation_id: UUID, text: str, agent_display_name: str) -> UUID:
    """Persist an agent message under a fresh `turn_id` and publish it."""
    turn_id = uuid4()
    await store.add_message(conversation_id, turn_id, role="agent", content=text)
    payload = MessagePayload(
        role="agent", text=text, sources=[], agent_display_name=agent_display_name
    )
    await events.publish(conversation_id, "message", payload.model_dump(mode="json"))
    return turn_id


async def return_to_bot(host: TurnHost, conversation_id: UUID, language: Language) -> None:
    """Hand the conversation back to Cardy: reset the checkpoint's handoff
    state, emit the fixed `back_with_cardy` message and `mode{bot}`.
    Raises `TurnBusy` if a turn holds the lock.
    """
    redis = get_redis()
    lock_key = f"turn:{conversation_id}"
    lock_id = str(uuid4())
    if not await redis.set(lock_key, lock_id, nx=True, ex=_LOCK_TTL_SECONDS):
        raise TurnBusy(f"a turn is running for conversation {conversation_id}")
    try:
        config = {"configurable": {"thread_id": str(conversation_id)}}
        await host.graph.aupdate_state(
            config,  # type: ignore[arg-type]
            {
                "mode": "bot",
                "pending": None,
                "intent_queue": [],
                "confirmation_token_id": None,
                "escalation_reason": None,
                "handoff_queue": None,
                "handoff_id": None,
                "handoff_evidence": [],
                "handoff_open_questions": [],
                "handoff_request": "",
                "clarification_failures": 0,
                "unauthorized_attempts": 0,
            },
        )
        text = get_template("back_with_cardy", language)
        await store.add_message(conversation_id, uuid4(), role="system", content=text)
        payload = MessagePayload(role="system", text=text, sources=[])
        await events.publish(conversation_id, "message", payload.model_dump(mode="json"))
        await publish_mode(conversation_id, "bot", None)
    finally:
        await redis.eval(_RELEASE_LOCK_SCRIPT, 1, lock_key, lock_id)
