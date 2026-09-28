"""Conversation routes (D14, D18): `POST /conversations`,
`POST /conversations/{id}/messages`, `GET /conversations/{id}/stream`.

`router` declares `require_role("customer")` and `require_csrf` at the
*router* level (R13, ADR-025), same convention `auth.py` set: a future route
added here can't forget either check. D18: agent access to `GET /stream`
arrives with the live-takeover backend (D4 G10) -- today every route here is
customer-only.

No route takes `customer_id` as a body, query or path field (R1): it always
comes from the `Session` the router-level `require_role` dependency already
decoded. `POST /messages` and `GET /stream` both additionally depend on
`get_owned_conversation` (R13): a conversation that doesn't exist or belongs
to another customer is `404 not_found`, before either route does anything
else.

`get_owned_conversation` lives here, in the API layer, not in
`app.domains.conversation` (human decision, T12): it needs
`identity.deps.get_session`, and `identity.deps` pulls in the whole
`identity.service` module (login/me's `customers.service` and
`identity.repository` included) at import time, which the
`conversation-no-repository` import-linter contract would flag as
conversation reaching bank data outside its tools registry -- even though
nothing here calls into either. Keeping the dependency in `app.api` avoids
touching that contract or `identity/service.py`.

See `docs/specs/d2-a-login-read-tools-api.md` "Contracts" -> the three
`/conversations` rows, D14, D18; `docs/solution-docs/04-contracts.md` §3
"Auth (ADR-025)", "SSE events".
"""

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from app.core import events
from app.core.telemetry import get_trace_id
from app.domains.conversation import store
from app.domains.conversation.runner import TurnInProgress, start_turn
from app.domains.conversation.store import ConversationRow
from app.domains.identity.deps import get_session, require_csrf, require_role
from app.domains.identity.models import Session

__all__ = ["router"]


async def get_owned_conversation(
    conversation_id: UUID,
    session: Annotated[Session, Depends(get_session)],
) -> ConversationRow:
    """The `{conversation_id}` path's conversation, scoped to the caller's
    own `customer_id` (R13, D18). Raises `404 not_found` -- same body either
    way -- when the row doesn't exist or belongs to a different customer.
    """
    conversation = await store.get_conversation(conversation_id)
    if conversation is None or conversation.customer_id != session.customer_id:
        raise HTTPException(status_code=404, detail="not_found")
    return conversation


router = APIRouter(
    prefix="/conversations",
    dependencies=[Depends(require_role("customer")), Depends(require_csrf)],
)

# The conversation's initial language hint when the request omits it (`04`
# lists `es | pt | mixed`, `es` first): `app.conversations.language` is
# nullable at the schema level for a future caller that genuinely doesn't
# know yet, but this route always has a value to write.
_DEFAULT_LANGUAGE: Literal["es"] = "es"

_PING_INTERVAL_SECONDS = 15


class CreateConversationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    language: Literal["es", "pt"] | None = None


class CreateConversationResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    conversation_id: UUID


class PostMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=2000)


class PostMessageResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    turn_id: UUID


@router.post("", response_model=CreateConversationResponse, status_code=201)
async def create_conversation(
    body: CreateConversationRequest,
    session: Annotated[Session, Depends(get_session)],
) -> CreateConversationResponse:
    """Start a new conversation for the caller's own `customer_id` (R1)."""

    conversation_id = await store.create_conversation(
        session.customer_id, body.language or _DEFAULT_LANGUAGE
    )
    return CreateConversationResponse(conversation_id=conversation_id)


@router.post("/{conversation_id}/messages", response_model=PostMessageResponse, status_code=202)
async def post_message(
    body: PostMessageRequest,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    conversation: Annotated[ConversationRow, Depends(get_owned_conversation)],
) -> PostMessageResponse:
    """Take the turn lock, persist the customer message and schedule the
    turn (D14). `409 turn_in_progress` when another turn already holds the
    lock for this conversation; `409 conversation_closed` once the customer
    said goodbye (the client starts a new conversation instead).
    """
    if conversation.status == "closed":
        raise HTTPException(status_code=409, detail="conversation_closed")

    try:
        turn_id = await start_turn(
            request.app.state.turn_host,
            session=session,
            conversation_id=conversation.id,
            text=body.text,
            trace_id=get_trace_id(),
        )
    except TurnInProgress as exc:
        raise HTTPException(status_code=409, detail="turn_in_progress") from exc
    return PostMessageResponse(turn_id=turn_id)


async def _sse_stream(stream: AsyncIterator[tuple[str, Any]]) -> AsyncIterator[str]:
    """`: connected` first, then one SSE frame per event, then a `: ping`
    comment after `_PING_INTERVAL_SECONDS` without one (D14).
    """

    yield ": connected\n\n"
    while True:
        try:
            event, data = await asyncio.wait_for(anext(stream), timeout=_PING_INTERVAL_SECONDS)
        except TimeoutError:
            yield ": ping\n\n"
            continue
        except StopAsyncIteration:
            return
        yield f"event: {event}\ndata: {json.dumps(data)}\n\n"


@router.get("/{conversation_id}/stream")
async def stream_conversation(
    conversation: Annotated[ConversationRow, Depends(get_owned_conversation)],
) -> StreamingResponse:
    """Subscribe to the conversation's event channel *before* the response
    is returned (D14): a client that posts a message right after opening the
    stream never misses that turn's events. Unsubscribes on client
    disconnect, same as any other exit from the `async with` block.
    """

    subscription = events.subscribe(conversation.id)
    stream = await subscription.__aenter__()

    async def _generate() -> AsyncIterator[str]:
        try:
            async for chunk in _sse_stream(stream):
                yield chunk
        finally:
            await subscription.__aexit__(None, None, None)

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
