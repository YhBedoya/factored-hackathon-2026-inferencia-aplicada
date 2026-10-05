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

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from app.api.v1.conversations import _sse_stream
from app.core import events
from app.core.config import get_settings
from app.core.errors import NotFound, ToolError
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
from app.domains.cards import service as cards_service
from app.domains.cards.schemas import (
    CardRequestDecision,
    CardRequestDecisionResult,
    CardRequestPanel,
    CardRequestView,
)
from app.domains.conversation import store
from app.domains.conversation.card_request_messages import (
    announce_decision,
    cancel_reason_label,
    render_decision,
)
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
from app.domains.customers import service as customers_service
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

_logger = structlog.get_logger(__name__)

_DECISION_TOOL = "cards.decide_card_request"

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
    # A linked card request must be decided before the conversation goes back to
    # the bot (AS9): the customer is waiting on that answer.
    block = detail.packet.card_request
    if block is not None:
        try:
            linked = await cards_service.get_request(block.request_id)
        except NotFound:
            linked = None
        if linked is not None and linked.status == "pending":
            raise HTTPException(status_code=409, detail="request_undecided")
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


async def _linked_request(detail: HandoffDetail) -> CardRequestView:
    """The card request this handoff's packet carries, or `404 not_found` when it
    has none, doesn't exist or belongs to another conversation."""
    block = detail.packet.card_request
    if block is None:
        raise HTTPException(status_code=404, detail="not_found")
    try:
        view = await cards_service.get_request(block.request_id)
    except NotFound as exc:
        raise HTTPException(status_code=404, detail="not_found") from exc
    if view.conversation_id != detail.summary.conversation_id:
        raise HTTPException(status_code=404, detail="not_found")
    return view


async def _claimed_handoff(handoff_id: UUID, session: Session) -> HandoffDetail:
    """The handoff, only for its claimant: `404 not_found` otherwise (R13)."""
    try:
        detail = await handoff_service.get_detail(handoff_id)
    except NotFound as exc:
        raise HTTPException(status_code=404, detail="not_found") from exc
    if not await handoff_service.is_claimed_by(detail.summary.conversation_id, session.account_id):
        raise HTTPException(status_code=404, detail="not_found")
    return detail


@router.get("/handoffs/{handoff_id}/card-request")
async def get_card_request(
    handoff_id: UUID, session: Annotated[Session, Depends(get_session)]
) -> CardRequestPanel:
    detail = await _claimed_handoff(handoff_id, session)
    view = await _linked_request(detail)
    language = detail.summary.language
    panel = await cards_service.build_panel(view.id, language)
    code = panel.request.reason_code
    if code is None:
        return panel
    # `cards` can't import the wording (it lives in `conversation`), so it is added here.
    request = panel.request.model_copy(update={"reason_label": cancel_reason_label(code, language)})
    return panel.model_copy(update={"request": request})


def _raise_decision_error(exc: ToolError) -> NoReturn:
    """Map `decide_request`'s errors to spec §5's codes."""
    if isinstance(exc, NotFound):
        raise HTTPException(status_code=404, detail="not_found") from exc
    if isinstance(exc, cards_service.AlreadyDecided | cards_service.BalanceNotZero):
        raise HTTPException(status_code=409, detail=exc.code) from exc
    if isinstance(
        exc,
        cards_service.DecisionNotAllowed
        | cards_service.LimitRequired
        | cards_service.LimitOutOfBounds
        | cards_service.DeclineReasonInvalid,
    ):
        raise HTTPException(status_code=422, detail=exc.code) from exc
    raise exc


@router.post("/handoffs/{handoff_id}/card-request/decision")
async def decide_card_request(
    handoff_id: UUID,
    body: CardRequestDecision,
    session: Annotated[Session, Depends(get_session)],
    idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
) -> CardRequestDecisionResult:
    try:
        detail = await handoff_service.get_detail(handoff_id)
    except NotFound as exc:
        raise HTTPException(status_code=404, detail="not_found") from exc
    # Only the claimant decides (R13): checked before anything can be written.
    if not await handoff_service.is_claimed_by(detail.summary.conversation_id, session.account_id):
        raise HTTPException(status_code=409, detail="not_claimant")
    view = await _linked_request(detail)
    audit = _audit(session, detail.summary, detail.packet.policy_version)

    async def before_write() -> None:
        # Fail-closed (D15): if this raises, the transaction rolls back unwritten.
        await audit.record(
            "tool_call",
            {
                "tool": _DECISION_TOOL,
                "request_id": str(view.id),
                "decision": body.decision,
                "credit_limit": body.credit_limit,
                "decline_reason": body.decline_reason,
            },
        )

    try:
        outcome = await cards_service.decide_request(
            view.id,
            session.account_id,
            body,
            decision_key=str(idempotency_key),
            before_write=before_write,
        )
    except ToolError as exc:
        _raise_decision_error(exc)
    if outcome.replayed:
        # Nothing was written, so nothing is audited or announced again (R-c).
        return CardRequestDecisionResult(request=outcome.request, verified=outcome.verified)

    decided = outcome.request
    try:
        await audit.record(
            "readback",
            {
                "tool": _DECISION_TOOL,
                "verified": outcome.verified,
                "readback": {
                    "status": decided.status,
                    "decision": decided.decision,
                    "product_id": decided.product_id,
                },
            },
        )
        await audit.record("tool_result", {"tool": _DECISION_TOOL, "verified": outcome.verified})
    except Exception:
        # The write is done: log and carry on rather than fail the click (D15).
        _logger.warning("audit.write_failed", tool=_DECISION_TOOL, type="readback")

    message_id: UUID | None = None
    if outcome.verified and decided.decision is not None:
        message_id = await _announce(detail, decided, session)
    return CardRequestDecisionResult(
        request=decided, verified=outcome.verified, message_id=message_id
    )


async def _announce(
    detail: HandoffDetail, decided: CardRequestView, session: Session
) -> UUID | None:
    """Render the decision template in code (R4) and post it as the claimant (R3)."""
    assert decided.decision is not None
    language = detail.summary.language
    profile = await customers_service.get_decision_profile(decided.customer_id)
    currency = policy_registry.get_policies().card_requests.currency_by_country[profile.country]
    last4 = ""
    balance = None
    credit_limit = decided.credit_limit
    if decided.product_id is not None:
        card = await cards_service.get_card_details(decided.customer_id, decided.product_id)
        last4, balance = card.last4, card.current_balance
        currency = card.currency
    text = render_decision(
        decided.decision,
        language,
        last4=last4,
        currency=currency,
        country=profile.country,
        card_kind=decided.card_kind,
        credit_limit=credit_limit,
        balance=balance,
    )
    return await announce_decision(
        decided.conversation_id,
        verified=True,
        decision=decided.decision,
        text=text,
        agent_display_name=await _display_name(session),
    )


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
