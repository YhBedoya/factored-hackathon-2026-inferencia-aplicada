"""The SSE stream survives its keep-alive ping (D14).

A ping used to cancel the pending read, which closed the event source: the
stream ended every idle `_PING_INTERVAL_SECONDS` and any event published
during the client's reconnect was lost (a staff decision message, for one).
"""

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import pytest

from app.api.v1 import conversations


async def _late_event(delay: float) -> AsyncIterator[tuple[str, Any]]:
    await asyncio.sleep(delay)
    yield "message", {"role": "agent", "text": "hola"}


async def _read_until_event() -> list[str]:
    chunks: list[str] = []
    async for chunk in conversations._sse_stream(_late_event(0.05)):
        chunks.append(chunk)
        if chunk.startswith("event:"):
            break
    return chunks


def test_event_after_a_ping_is_still_delivered(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(conversations, "_PING_INTERVAL_SECONDS", 0.01)
    chunks = asyncio.run(_read_until_event())

    assert ": ping\n\n" in chunks
    assert chunks[-1].startswith("event: message\n")
