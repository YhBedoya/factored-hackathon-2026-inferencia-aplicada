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

__all__ = [
    "channel",
    "handoff_channel",
    "publish",
    "publish_handoff",
    "subscribe",
    "subscribe_handoffs",
]

_HANDOFF_PATTERN = "handoff:*"


def channel(conversation_id: UUID) -> str:
    """The pub/sub channel name for one conversation (D14)."""
    return f"conv:{conversation_id}"


async def publish(conversation_id: UUID, event: str, data: Any) -> None:
    """Publish one `{"event": ..., "data": ...}` JSON envelope (D14)."""
    envelope = json.dumps({"event": event, "data": data})
    await get_redis().publish(channel(conversation_id), envelope)


def handoff_channel(queue: str) -> str:
    """The pub/sub channel name for one handoff queue (D12, D17)."""
    return f"handoff:{queue}"


async def publish_handoff(queue: str, event: str, data: Any) -> None:
    """Publish one `{"event": ..., "data": ...}` envelope on a handoff queue channel (D12)."""
    envelope = json.dumps({"event": event, "data": data})
    await get_redis().publish(handoff_channel(queue), envelope)


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


@asynccontextmanager
async def subscribe_handoffs(queue: str | None) -> AsyncIterator[AsyncIterator[tuple[str, Any]]]:
    """Subscribe to one queue's handoff channel, or to every queue
    (`psubscribe("handoff:*")`) when `queue is None` (D17). Same contract as
    `subscribe`: subscribed on entry, always unsubscribed and closed on exit.
    """
    pubsub = get_redis().pubsub()
    if queue is None:
        await pubsub.psubscribe(_HANDOFF_PATTERN)
    else:
        await pubsub.subscribe(handoff_channel(queue))
    try:
        yield _events(pubsub)
    finally:
        if queue is None:
            await pubsub.punsubscribe(_HANDOFF_PATTERN)
        else:
            await pubsub.unsubscribe(handoff_channel(queue))
        await pubsub.aclose()  # type: ignore[no-untyped-call]  # redis-py's `aclose` has no stub annotation


async def _events(pubsub: PubSub) -> AsyncIterator[tuple[str, Any]]:
    """Decode `pubsub.listen()`'s messages, skipping the subscribe/unsubscribe
    acks (`type` not in `message|pmessage`) that `listen()` also yields.
    """
    async for raw in pubsub.listen():
        if raw["type"] not in ("message", "pmessage"):
            continue
        envelope = json.loads(raw["data"])
        yield envelope["event"], envelope["data"]
