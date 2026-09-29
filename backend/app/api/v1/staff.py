"""Staff routes (D2, D5, D6): `/staff/*`, agent-only.

`router` declares `require_role("agent")` and `require_csrf` at the
*router* level (R13, ADR-025), the same convention `auth.py` and
`conversations.py` set: a future route added here can't forget either
check. `GET /staff/me` is the only route this card actually implements
(`identity_service.staff_me`); the other six exist only so OpenAPI and the
generated client are final today (D2) -- their bodies raise `501
not_implemented` until A3/A4 land the real `HandoffPort` and the agent
relay. Each still declares its real request/response model, so the client
generated against this OpenAPI never needs to change shape once A wires the
body in.

No route here takes `customer_id` (R1): a staff session never carries one
(D4), and nothing here reads or writes one either.

`GET /staff/conversations/{conversation_id}/stream` is D6's agent-side
stream, distinct from the customer-only `GET /conversations/{id}/stream` in
`conversations.py` -- an agent reaches the customer's turn events only
through this route, once claimed.

See `docs/specs/d4-b-disputes-handoff-screens.md` D2, D5, D6, "Contracts"
-> "HTTP".
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from app.domains.handoff.schemas import (
    AgentMessageRequest,
    AgentMessageResponse,
    HandoffDetail,
    HandoffListResponse,
    HandoffSummary,
)
from app.domains.identity import service as identity_service
from app.domains.identity.deps import get_session, require_csrf, require_role
from app.domains.identity.models import Session, StaffMeResponse
from app.domains.localization.format import Queue

__all__ = ["router"]

router = APIRouter(
    prefix="/staff",
    dependencies=[Depends(require_role("agent")), Depends(require_csrf)],
)


@router.get("/me", response_model=StaffMeResponse)
async def staff_me(session: Annotated[Session, Depends(get_session)]) -> StaffMeResponse:
    """The caller's own agent profile (D3, D5): display name only, the same
    way `GET /auth/me` reflects a customer session back.
    """

    return await identity_service.staff_me(session)


@router.get("/handoffs", response_model=HandoffListResponse)
async def list_handoffs(queue: Queue | None = None) -> HandoffListResponse:
    """The live inbox (D20). A implements this against the real
    `HandoffPort`; the inbox filter and order are Dev A's (spec open item 3).
    """

    raise HTTPException(status_code=501, detail="not_implemented")


@router.get("/handoffs/{handoff_id}", response_model=HandoffDetail)
async def get_handoff(handoff_id: UUID) -> HandoffDetail:
    """One packet's full detail. A implements this against the real
    `HandoffPort`.
    """

    raise HTTPException(status_code=501, detail="not_implemented")


@router.post("/handoffs/{handoff_id}/claim", response_model=HandoffDetail)
async def claim_handoff(handoff_id: UUID) -> HandoffDetail:
    """Claim a queued handoff for the caller. A implements the claimed-by
    check behind `409 already_claimed`.
    """

    raise HTTPException(status_code=501, detail="not_implemented")


@router.post("/handoffs/{handoff_id}/return", response_model=HandoffSummary)
async def return_handoff(handoff_id: UUID) -> HandoffSummary:
    """Return a claimed handoff to the bot. A implements the claimed-by
    check behind `409 not_claimed`.
    """

    raise HTTPException(status_code=501, detail="not_implemented")


@router.post(
    "/conversations/{conversation_id}/messages",
    response_model=AgentMessageResponse,
    status_code=202,
)
async def post_agent_message(
    conversation_id: UUID, body: AgentMessageRequest
) -> AgentMessageResponse:
    """An agent's message into a claimed conversation. A implements the
    relay to the customer's `/stream` and the claimed-by check.
    """

    raise HTTPException(status_code=501, detail="not_implemented")


@router.get("/conversations/{conversation_id}/stream")
async def stream_agent_conversation(conversation_id: UUID) -> StreamingResponse:
    """The agent-side SSE stream for a claimed conversation (D6, `04` §3
    events). A implements the claimed-by check and the relay.
    """

    raise HTTPException(status_code=501, detail="not_implemented")
