"""Staff routes (D4-A D16), all under `/staff`.

T23 adds `GET /staff/me` and `POST /staff/logout`. T24 adds the handoff queue
(`GET /staff/handoffs`, `GET /staff/handoffs/stream`,
`GET /staff/handoffs/{id}`, `POST /staff/handoffs/{id}/claim`,
`POST /staff/handoffs/{id}/return`) and the claimed-conversation routes
(`GET|POST /staff/conversations/{id}/messages`,
`GET /staff/conversations/{id}/stream`), each of the latter depending on
`get_claimed_conversation`.

D7-A adds the read-only oversight routes: `GET /staff/conversations` (filtered
list), `GET /staff/conversations/{id}/timeline` (the one route on
`get_any_conversation`: no claim needed, still agent/admin) and
`GET /staff/system`.

The router declares `require_role("agent", "admin")` and `require_csrf` at
the router level (R13, ADR-025), so a route added here can't forget either.

See `docs/specs/d4-a-escalation-handoff-deploy.md` D16 and "Contracts" ->
"Staff API".
"""

import hashlib
from collections.abc import AsyncIterator
from datetime import date
from typing import Annotated, Any, Literal, NoReturn
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from app.api.v1.conversations import _sse_stream
from app.core import events
from app.core.config import get_settings
from app.core.errors import NotFound
from app.core.llm.registry import MODEL_REGISTRY, STEP_PROVIDER, TEMPERATURE, Step
from app.core.llm.settings import LLMSettings
from app.core.telemetry import get_trace_id
from app.domains.audit import timeline
from app.domains.audit.schemas import (
    ConversationPage,
    ConversationTimeline,
    PolicyFileInfo,
    StepInfo,
    SystemInfo,
)
from app.domains.audit.service import AuditRecorder
from app.domains.conversation import store
from app.domains.conversation.nodes.compose import _PROMPT as _COMPOSE_PROMPT
from app.domains.conversation.nodes.handoff_summary import _PROMPT as _HANDOFF_SUMMARY_PROMPT
from app.domains.conversation.nodes.understand import _PROMPT as _NLU_PROMPT
from app.domains.conversation.store import ConversationRow
from app.domains.conversation.takeover import (
    TurnBusy,
    publish_mode,
    relay_agent_message,
    return_to_bot,
)
from app.domains.handoff import service as handoff_service
from app.domains.handoff.schemas import (
    HandoffDetail,
    HandoffStatus,
    HandoffSummary,
    TranscriptMessage,
)
from app.domains.identity import service as identity_service
from app.domains.identity.deps import get_session, require_csrf, require_role
from app.domains.identity.models import Session
from app.domains.policy import registry as policy_registry

__all__ = ["get_any_conversation", "get_claimed_conversation", "router"]

router = APIRouter(
    prefix="/staff",
    dependencies=[Depends(require_role("agent", "admin")), Depends(require_csrf)],
)

_VALID_STATUSES: tuple[HandoffStatus, ...] = ("queued", "claimed", "returned")


class RelayMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=2000)


class RelayMessageResponse(BaseModel):
    message_id: str


async def get_claimed_conversation(
    conversation_id: UUID,
    session: Annotated[Session, Depends(get_session)],
) -> ConversationRow:
    """The `{conversation_id}` path's conversation, only while it has an open
    handoff claimed by the caller (R13, D16). `404 not_found` -- same body
    either way -- for a missing conversation, an unclaimed one or another
    agent's.
    """
    conversation = await store.get_conversation(conversation_id)
    if conversation is None or not await handoff_service.is_claimed_by(
        conversation_id, session.account_id
    ):
        raise HTTPException(status_code=404, detail="not_found")
    return conversation


async def get_any_conversation(conversation_id: UUID) -> ConversationRow:
    """The `{conversation_id}` path's conversation, claimed or not (D16). Used
    only by the read-only timeline route (R13 exception, checked by
    `test_r13_routes`); role is still agent/admin from the router.
    `404 not_found` for a missing conversation.
    """
    conversation = await store.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="not_found")
    return conversation


def _raise_handoff_error(exc: Exception) -> NoReturn:
    """Map the handoff service's errors to the API's (T11: no `code` attr)."""
    if isinstance(exc, NotFound):
        raise HTTPException(status_code=404, detail="not_found") from exc
    if isinstance(exc, handoff_service.AlreadyClaimed):
        raise HTTPException(status_code=409, detail="already_claimed") from exc
    if isinstance(exc, handoff_service.HandoffClosed):
        raise HTTPException(status_code=409, detail="handoff_closed") from exc
    if isinstance(exc, handoff_service.NotClaimant):
        raise HTTPException(status_code=409, detail="not_claimant") from exc
    raise exc


async def _display_name(session: Session) -> str:
    return (await identity_service.staff_me(session)).display_name


def _audit(
    session: Session, detail_or_summary: HandoffSummary, policy_version: str
) -> AuditRecorder:
    return AuditRecorder(
        conversation_id=detail_or_summary.conversation_id,
        turn_id=uuid4(),
        trace_id=get_trace_id(),
        policy_version=policy_version,
        actor=f"agent:{session.account_id}",
    )


async def _sse_response(subscription: Any) -> StreamingResponse:
    """Subscribe *before* returning (D14), unsubscribe on any exit."""
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


@router.get("/handoffs")
async def list_handoffs(
    queue: str | None = None,
    status: str = "queued,claimed",
) -> list[HandoffSummary]:
    statuses = [s for s in status.split(",") if s]
    if not statuses or any(s not in _VALID_STATUSES for s in statuses):
        raise HTTPException(status_code=422, detail="invalid_status")
    return await handoff_service.list_handoffs(
        [queue] if queue else None,
        statuses,  # type: ignore[arg-type]  # validated against _VALID_STATUSES
    )


@router.get("/handoffs/stream")
async def stream_handoffs(queue: Annotated[str | None, Query()] = None) -> StreamingResponse:
    return await _sse_response(events.subscribe_handoffs(queue))


@router.get("/handoffs/{handoff_id}")
async def get_handoff(handoff_id: UUID) -> HandoffDetail:
    try:
        return await handoff_service.get_detail(handoff_id)
    except NotFound as exc:
        _raise_handoff_error(exc)


@router.post("/handoffs/{handoff_id}/claim")
async def claim_handoff(
    handoff_id: UUID, session: Annotated[Session, Depends(get_session)]
) -> HandoffDetail:
    try:
        detail = await handoff_service.claim(handoff_id, session.account_id)
    except (NotFound, handoff_service.AlreadyClaimed, handoff_service.HandoffClosed) as exc:
        _raise_handoff_error(exc)
    display_name = await _display_name(session)
    await publish_mode(detail.summary.conversation_id, "human", display_name)
    await _audit(session, detail.summary, detail.packet.policy_version).record(
        "handoff",
        {"event": "claimed", "handoff_id": str(handoff_id), "queue": detail.summary.queue},
    )
    return detail


@router.post("/handoffs/{handoff_id}/return")
async def return_handoff(
    handoff_id: UUID,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
) -> HandoffSummary:
    try:
        detail = await handoff_service.get_detail(handoff_id)
    except NotFound as exc:
        _raise_handoff_error(exc)
    # Only the claimant may flip the mode: check before `return_to_bot` so a
    # non-claimant can't change anything.
    if not await handoff_service.is_claimed_by(detail.summary.conversation_id, session.account_id):
        raise HTTPException(status_code=409, detail="not_claimant")
    # Mode first (under the turn lock), then close the handoff: a busy lock
    # leaves everything unchanged and the agent retries.
    try:
        await return_to_bot(
            request.app.state.turn_host,
            detail.summary.conversation_id,
            detail.summary.language,
        )
    except TurnBusy as exc:
        raise HTTPException(status_code=409, detail="turn_in_progress") from exc
    try:
        summary = await handoff_service.return_handoff(handoff_id, session.account_id)
    except (NotFound, handoff_service.NotClaimant, handoff_service.HandoffClosed) as exc:
        _raise_handoff_error(exc)
    await _audit(session, summary, detail.packet.policy_version).record(
        "handoff",
        {"event": "returned", "handoff_id": str(handoff_id), "queue": summary.queue},
    )
    return summary


@router.get("/conversations/{conversation_id}/messages")
async def list_conversation_messages(
    conversation: Annotated[ConversationRow, Depends(get_claimed_conversation)],
) -> list[TranscriptMessage]:
    rows = await store.list_messages(conversation.id)
    return [
        TranscriptMessage.model_validate(
            {"role": row.role, "text": row.content, "created_at": row.created_at}
        )
        for row in rows
    ]


@router.post("/conversations/{conversation_id}/messages", status_code=201)
async def post_conversation_message(
    body: RelayMessageRequest,
    conversation: Annotated[ConversationRow, Depends(get_claimed_conversation)],
    session: Annotated[Session, Depends(get_session)],
) -> RelayMessageResponse:
    message_id = await relay_agent_message(conversation.id, body.text, await _display_name(session))
    return RelayMessageResponse(message_id=str(message_id))


@router.get("/conversations/{conversation_id}/stream")
async def stream_conversation(
    conversation: Annotated[ConversationRow, Depends(get_claimed_conversation)],
) -> StreamingResponse:
    return await _sse_response(events.subscribe(conversation.id))


@router.get("/conversations")
async def list_conversations(
    language: Literal["es", "pt"] | None = None,
    country: Literal["MX", "CO", "AR"] | None = None,
    intent: str | None = None,
    outcome: Annotated[
        str | None, Query(pattern=r"^(resolved|clarified|abstained|handoff(:.+)?)$")
    ] = None,
    escalation: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ConversationPage:
    return await timeline.list_conversations(
        language=language,
        country=country,
        intent=intent,
        outcome=outcome,
        escalation=escalation,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        offset=offset,
    )


@router.get("/conversations/{conversation_id}/timeline")
async def get_conversation_timeline(
    conversation: Annotated[ConversationRow, Depends(get_any_conversation)],
) -> ConversationTimeline:
    try:
        return await timeline.get_timeline(conversation.id)
    except NotFound as exc:
        raise HTTPException(status_code=404, detail="not_found") from exc


@router.get("/system")
async def get_system() -> SystemInfo:
    settings = get_settings()
    llm_provider = LLMSettings().llm_provider
    prompts: dict[Step, str] = {
        "nlu": _NLU_PROMPT.label,
        "compose": _COMPOSE_PROMPT.label,
        "handoff_summary": _HANDOFF_SUMMARY_PROMPT.label,
    }
    steps = [
        StepInfo(
            step=step,
            model_id=MODEL_REGISTRY[step][STEP_PROVIDER.get(step, llm_provider)],
            temperature=TEMPERATURE[step],
            prompt_version=label,
        )
        for step, label in prompts.items()
    ]
    policy_files = sorted(policy_registry._DEFAULT_POLICIES_DIR.glob("*.yaml"))
    return SystemInfo(
        git_sha=settings.git_sha,
        app_env=settings.app_env,
        llm_provider=llm_provider,
        llm_disabled=settings.llm_disabled,
        steps=steps,
        policy_hash=policy_registry.get_policies().hash,
        policies=[
            PolicyFileInfo(file=path.name, sha256=hashlib.sha256(path.read_bytes()).hexdigest())
            for path in policy_files
        ],
    )
