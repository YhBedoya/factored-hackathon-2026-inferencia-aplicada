"""Conversation routes (D14, D18): `POST /conversations`,
`POST /conversations/{id}/messages`, `POST /conversations/{id}/confirmations/{token_id}`
(D6, D7), `GET /conversations/{id}/stream`.

`router` declares `require_role("customer")` and `require_csrf` at the
*router* level (R13, ADR-025), same convention `auth.py` set: a future route
added here can't forget either check. D18: agent access to `GET /stream`
arrives with the live-takeover backend (D4 G10) -- today every route here is
customer-only.

No route takes `customer_id` as a body, query or path field (R1): it always
comes from the `Session` the router-level `require_role` dependency already
decoded. Every `/{conversation_id}/...` route additionally depends on
`get_owned_conversation` (R13): a conversation that doesn't exist or belongs
to another customer is `404 not_found`, before the route body does anything
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

`POST /confirmations/{token_id}` (D7) checks two things before it schedules
anything, so a used, foreign or merely-issued-but-not-checkpointed token
never starts a turn (R2): `RedisConfirmationStore.is_open` (the plan still
exists and belongs to this customer + conversation) and
`runner.checkpointed_confirmation_token` (this token is the one the graph's
last checkpoint is actually waiting on). Either failing is `409
confirmation_invalid`, same status as a foreign token, so a client can't
distinguish "wrong owner" from "already used" from "not what the plan is
waiting on" by status code alone. The executor's own R2 checks (`04` §7)
stay as the second gate once a turn does run.

See `docs/specs/d2-a-login-read-tools-api.md` "Contracts" -> the three
`/conversations` rows, D14, D18; `docs/specs/d3-a-guardrails-write-path.md`
D6, D7, "Contracts" -> `/messages`, `/confirmations`;
`docs/solution-docs/04-contracts.md` §3 "Auth (ADR-025)", "SSE events".
"""

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal, Self
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core import events
from app.core.config import get_settings
from app.core.redis import get_redis
from app.core.telemetry import get_trace_id
from app.domains.conversation import store
from app.domains.conversation.graph import CardSelection, ConfirmationDecision, TxSelection
from app.domains.conversation.runner import (
    TurnInProgress,
    checkpointed_confirmation_token,
    checkpointed_form_pause,
    checkpointed_offer,
    checkpointed_otp_pause,
    checkpointed_replacement_offer,
    start_turn,
)
from app.domains.conversation.store import ConversationRow
from app.domains.conversation.welcome import post_welcome
from app.domains.customers import service as customers_service
from app.domains.customers.schemas import ProfileFormView, ProfileValues
from app.domains.identity.deps import get_session, require_csrf, require_role
from app.domains.identity.models import Session
from app.domains.policy.confirmation_redis import RedisConfirmationStore
from app.domains.safety.vault import PostgresPiiVault

__all__ = ["router"]


def _customer_id(session: Session) -> str:
    """Narrow `session.customer_id` for the type checker. `None` means a
    staff session, which `require_role("customer")` already refused, so
    this is unreachable in practice (D15).
    """
    if session.customer_id is None:
        raise HTTPException(status_code=403, detail="forbidden_role")
    return session.customer_id


async def get_owned_conversation(
    conversation_id: UUID,
    session: Annotated[Session, Depends(get_session)],
) -> ConversationRow:
    """The `{conversation_id}` path's conversation, scoped to the caller's
    own `customer_id` (R13, D18). Raises `404 not_found` -- same body either
    way -- when the row doesn't exist or belongs to a different customer.
    """
    conversation = await store.get_conversation(conversation_id)
    if conversation is None or conversation.customer_id != _customer_id(session):
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

# D11 key TTLs: the account key only has to outlive its UTC day, the
# conversation key outlives any realistic chat.
_CONV_TURNS_TTL_SECONDS = 7 * 24 * 3600
_ACCT_TURNS_TTL_SECONDS = 2 * 24 * 3600


def _turn_cap_keys(session: Session, conversation: ConversationRow) -> tuple[str, str]:
    day = datetime.now(UTC).strftime("%Y-%m-%d")
    return f"turns:conv:{conversation.id}", f"turns:acct:{session.account_id}:{day}"


async def _check_turn_caps(session: Session, conversation: ConversationRow) -> None:
    """D11: `429 turn_cap_reached` at or over either cap. Bot mode only:
    human-mode posts are the customer talking to a person, not LLM spend.
    """
    if conversation.mode != "bot":
        return
    settings = get_settings()
    conv_key, acct_key = _turn_cap_keys(session, conversation)
    conv_count, acct_count = await get_redis().mget(conv_key, acct_key)
    if (
        int(conv_count or 0) >= settings.turn_cap_per_conversation
        or int(acct_count or 0) >= settings.turn_cap_per_account_day
    ):
        raise HTTPException(status_code=429, detail="turn_cap_reached")


async def _count_turn(session: Session, conversation: ConversationRow) -> None:
    """D11: count a scheduled bot-mode turn, only after `start_turn` returned."""
    if conversation.mode != "bot":
        return
    conv_key, acct_key = _turn_cap_keys(session, conversation)
    async with get_redis().pipeline(transaction=True) as pipe:
        pipe.incr(conv_key)
        pipe.expire(conv_key, _CONV_TURNS_TTL_SECONDS)
        pipe.incr(acct_key)
        pipe.expire(acct_key, _ACCT_TURNS_TTL_SECONDS)
        await pipe.execute()


class CreateConversationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    language: Literal["es", "pt"] | None = None
    welcome: bool = False


class WelcomeMessage(BaseModel):
    model_config = ConfigDict(frozen=True)

    text: str


class CreateConversationResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    conversation_id: UUID
    welcome: WelcomeMessage | None = None


class PostMessageRequest(BaseModel):
    """`{text}` for a typed turn, `{resume: "step_up"}` for the OTP-resume
    turn (D6; `"step_up_cancel"` is Cancel on any OTP pause, S2: agent pause -> `agent_step_up`,
    pipeline pause -> `otp_cancel`),
    `{selection: {tx_ids}}` for the D4-B pick turn (D7), or
    `{card_selection: {card_ids}}` for the replacement picker -- exactly one
    of the four, or `422`. Only `text` is persisted as a customer message.
    """

    model_config = ConfigDict(extra="forbid")

    text: str | None = Field(default=None, min_length=1, max_length=2000)
    resume: Literal["step_up", "step_up_cancel"] | None = None
    selection: TxSelection | None = None
    card_selection: CardSelection | None = None

    @model_validator(mode="after")
    def _exactly_one(self) -> Self:
        set_count = sum(
            value is not None
            for value in (self.text, self.resume, self.selection, self.card_selection)
        )
        if set_count != 1:
            raise ValueError("exactly one of text, resume, selection or card_selection must be set")
        return self


class PostMessageResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    turn_id: UUID


class ConfirmationRequest(BaseModel):
    """`POST /confirmations/{token_id}` body (D7)."""

    model_config = ConfigDict(extra="forbid")

    decision: Literal["confirm", "cancel"]


@router.post("", response_model=CreateConversationResponse, status_code=201)
async def create_conversation(
    body: CreateConversationRequest,
    session: Annotated[Session, Depends(get_session)],
) -> CreateConversationResponse:
    """Start a new conversation for the caller's own `customer_id` (R1)."""

    conversation_id = await store.create_conversation(
        _customer_id(session), body.language or _DEFAULT_LANGUAGE
    )
    if not body.welcome:
        return CreateConversationResponse(conversation_id=conversation_id)
    text = await post_welcome(
        conversation_id, session=session, language=body.language or _DEFAULT_LANGUAGE
    )
    return CreateConversationResponse(
        conversation_id=conversation_id, welcome=WelcomeMessage(text=text)
    )


@router.post("/{conversation_id}/messages", response_model=PostMessageResponse, status_code=202)
async def post_message(
    body: PostMessageRequest,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    conversation: Annotated[ConversationRow, Depends(get_owned_conversation)],
) -> PostMessageResponse:
    """Take the turn lock, persist the customer message (a typed turn only,
    D6) and schedule the turn (D14). `409 turn_in_progress` when another turn
    already holds the lock for this conversation; `409 conversation_closed`
    once the customer said goodbye (the client starts a new conversation
    instead).

    D7's pick gate: a `selection` body is checked against this
    conversation's own last-checkpointed `pending` and offer
    (`runner.checkpointed_offer`, T7 -- generalized from D4-B's
    `checkpointed_dispute` to also cover `decline_explain`'s single-pick,
    D3) *before* anything is scheduled -- paused at
    `awaiting_slot == "transactions"`, every picked id actually offered,
    and exactly one id when the offer was single-pick (`multi = False`) --
    else `409 selection_invalid` and no turn runs (R1: a customer can't
    claim a transaction that was never offered). The flow re-checks the
    same rule once a turn does run, as a second gate.
    """
    if conversation.status == "closed":
        raise HTTPException(status_code=409, detail="conversation_closed")

    host = request.app.state.turn_host
    if body.selection is not None:
        pending, offered, multi = await checkpointed_offer(host, conversation.id)
        tx_ids = body.selection.tx_ids
        selection_open = (
            pending is not None
            and pending["awaiting_slot"] == "transactions"
            and set(tx_ids) <= offered
            and (multi or len(tx_ids) == 1)
        )
        if not selection_open:
            raise HTTPException(status_code=409, detail="selection_invalid")
    if body.card_selection is not None or body.text is not None:
        # Replacement picker gates (D32, D33): read the checkpoint only for
        # these two bodies. An empty `card_ids` is a valid decline.
        pending, offered_cards = await checkpointed_replacement_offer(host, conversation.id)
        at_picker = pending is not None and pending["awaiting_slot"] == "replacement_cards"
        if body.card_selection is not None:
            if not (at_picker and set(body.card_selection.card_ids) <= offered_cards):
                raise HTTPException(status_code=409, detail="selection_invalid")
        elif at_picker:
            raise HTTPException(status_code=409, detail="selection_required")

    if body.resume == "step_up_cancel" or body.text is not None:
        # S2 D15/D17/D30: Cancel works at any OTP pause; typed text is refused only at
        # the agent's (a pipeline OTP pause takes text as today). One checkpoint read.
        otp_pause = await checkpointed_otp_pause(host, conversation.id)
        if body.resume == "step_up_cancel" and otp_pause is None:
            raise HTTPException(status_code=409, detail="cancel_invalid")
        if body.text is not None and otp_pause == "agent":
            raise HTTPException(status_code=409, detail="otp_required")

    if body.text is not None and await checkpointed_form_pause(host, conversation.id):
        # D9-C D11: typed text at the profile form is refused, the pause stays.
        raise HTTPException(status_code=409, detail="form_required")

    await _check_turn_caps(session, conversation)
    try:
        turn_id = await start_turn(
            host,
            session=session,
            conversation_id=conversation.id,
            trace_id=get_trace_id(),
            text=body.text,
            resume=body.resume,
            selection=body.selection,
            card_selection=body.card_selection,
        )
    except TurnInProgress as exc:
        raise HTTPException(status_code=409, detail="turn_in_progress") from exc
    await _count_turn(session, conversation)
    return PostMessageResponse(turn_id=turn_id)


class ProfileFormValues(BaseModel):
    """The five editable values as submitted (D9-C D11). Never logged, persisted as a
    message or sent to the LLM: they go to the vault only (R5)."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    email: str = Field(max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    mobile_phone: str = Field(pattern=r"^\+?[0-9][0-9 ()\-]{5,19}$")
    address: str = Field(min_length=1, max_length=300)
    occupation: str = Field(min_length=1, max_length=120)
    estimated_monthly_income: Decimal = Field(gt=0, max_digits=14, decimal_places=2)


class ProfileFormSubmit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["submit"]
    values: ProfileFormValues


class ProfileFormCancel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["cancel"]


ProfileFormRequest = Annotated[ProfileFormSubmit | ProfileFormCancel, Field(discriminator="action")]


@router.get("/{conversation_id}/profile-form", response_model=ProfileFormView)
async def get_profile_form(
    request: Request,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    conversation: Annotated[ConversationRow, Depends(get_owned_conversation)],
) -> ProfileFormView:
    """The form's initial view for the session's customer (R1). `409 form_not_open`
    unless the checkpoint is paused at the form. Never cached or persisted."""
    if not await checkpointed_form_pause(request.app.state.turn_host, conversation.id):
        raise HTTPException(status_code=409, detail="form_not_open")
    response.headers["Cache-Control"] = "no-store"
    language: Literal["es", "pt"] = "pt" if conversation.language == "pt" else "es"
    view = await customers_service.get_profile_form(_customer_id(session), language)
    # The kind lives in the checkpoint, so a re-opened form (after a reload) titles itself.
    state = await request.app.state.turn_host.graph.aget_state(
        {"configurable": {"thread_id": str(conversation.id)}}
    )
    kind = state.values.get("card_request_kind")
    return view.model_copy(update={"card_kind": kind}) if kind in ("credit", "debit") else view


@router.post("/{conversation_id}/profile-form", response_model=PostMessageResponse, status_code=202)
async def post_profile_form(
    body: ProfileFormRequest,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    conversation: Annotated[ConversationRow, Depends(get_owned_conversation)],
) -> PostMessageResponse:
    """Submit or cancel the profile form (D9-C D11). A submit stages only the
    *changed* values in the vault and passes their names to the turn; the values
    never enter the message, `ui_payload`, LLM input or checkpoint (R5).
    """
    host = request.app.state.turn_host
    if not await checkpointed_form_pause(host, conversation.id):
        raise HTTPException(status_code=409, detail="form_not_open")
    customer_id = _customer_id(session)
    await _check_turn_caps(session, conversation)

    changed: list[str] | None = None
    if isinstance(body, ProfileFormSubmit):
        values = ProfileValues(**body.values.model_dump())
        fields = await customers_service.changed_fields(customer_id, values)
        raw = values.model_dump()
        await PostgresPiiVault(conversation.id).stage_form_values(
            {field: str(raw[field]) for field in fields}
        )
        changed = list(fields)
    try:
        turn_id = await start_turn(
            host,
            session=session,
            conversation_id=conversation.id,
            trace_id=get_trace_id(),
            resume="profile_form" if changed is not None else "profile_form_cancel",
            form_changed_fields=changed,
        )
    except TurnInProgress as exc:
        raise HTTPException(status_code=409, detail="turn_in_progress") from exc
    await _count_turn(session, conversation)
    return PostMessageResponse(turn_id=turn_id)


@router.post(
    "/{conversation_id}/confirmations/{token_id}",
    response_model=PostMessageResponse,
    status_code=202,
)
async def post_confirmation(
    token_id: str,
    body: ConfirmationRequest,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    conversation: Annotated[ConversationRow, Depends(get_owned_conversation)],
) -> PostMessageResponse:
    """Resolve a button confirm/cancel (D7). Before scheduling anything,
    checks that `token_id` is still an open plan owned by this customer and
    conversation (`RedisConfirmationStore.is_open`) *and* is the token the
    graph's last checkpoint actually paused on
    (`runner.checkpointed_confirmation_token`) -- either failing is `409
    confirmation_invalid`, and no turn is scheduled. `409 turn_in_progress`
    works the same as on `/messages`.
    """

    host = request.app.state.turn_host
    confirmation_store = RedisConfirmationStore(_customer_id(session), str(conversation.id))
    is_open = await confirmation_store.is_open(token_id)
    checkpointed_token = await checkpointed_confirmation_token(host, conversation.id)
    if not is_open or checkpointed_token != token_id:
        raise HTTPException(status_code=409, detail="confirmation_invalid")

    await _check_turn_caps(session, conversation)
    try:
        turn_id = await start_turn(
            host,
            session=session,
            conversation_id=conversation.id,
            trace_id=get_trace_id(),
            confirmation=ConfirmationDecision(token_id=token_id, decision=body.decision),
        )
    except TurnInProgress as exc:
        raise HTTPException(status_code=409, detail="turn_in_progress") from exc
    await _count_turn(session, conversation)
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
