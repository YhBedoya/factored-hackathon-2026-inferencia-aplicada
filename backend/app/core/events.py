"""Redis pub/sub for the conversation event stream (D14).

Strict-typed, no domain import: this module only reaches Redis through
`app.core.redis.get_redis()`. It knows nothing about conversations, messages
or turns beyond the `conversation_id` used to name the channel -- the API
layer (`POST /messages`, `GET /stream`) decides what `event`/`data` to send
and how to interpret what comes back.

Channel name: `conv:<conversation_id>` (D14). Each publish is one JSON
envelope `{"event": ..., "data": ...}`; `subscribe` hands back the decoded
`(event, data)` pairs so no caller has to touch the envelope shape itself.
"""

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

from redis.asyncio.client import PubSub

from app.core.redis import get_redis

__all__ = ["channel", "publish", "subscribe"]


def channel(conversation_id: UUID) -> str:
    """The pub/sub channel name for one conversation (D14)."""
    return f"conv:{conversation_id}"


async def publish(conversation_id: UUID, event: str, data: Any) -> None:
    """Publish one `{"event": ..., "data": ...}` JSON envelope (D14)."""
    envelope = json.dumps({"event": event, "data": data})
    await get_redis().publish(channel(conversation_id), envelope)


@asynccontextmanager
async def subscribe(conversation_id: UUID) -> AsyncIterator[AsyncIterator[tuple[str, Any]]]:
    """Subscribe to one conversation's channel for the life of the `async
    with` block (D14). Already subscribed by the time the block is entered;
    yields an async iterator of `(event, data)` pairs decoded from each
    envelope. Always unsubscribes and closes its `PubSub` on exit, including
    when the caller breaks out early or raises.
    """
    name = channel(conversation_id)
    pubsub = get_redis().pubsub()
    await pubsub.subscribe(name)
    try:
        yield _events(pubsub)
    finally:
        await pubsub.unsubscribe(name)
        await pubsub.aclose()  # type: ignore[no-untyped-call]  # redis-py's `aclose` has no stub annotation


async def _events(pubsub: PubSub) -> AsyncIterator[tuple[str, Any]]:
    """Decode `pubsub.listen()`'s messages, skipping the subscribe/unsubscribe
    acks (`type != "message"`) that `listen()` also yields.
    """
    async for raw in pubsub.listen():
        if raw["type"] != "message":
            continue
        envelope = json.loads(raw["data"])
        yield envelope["event"], envelope["data"]
