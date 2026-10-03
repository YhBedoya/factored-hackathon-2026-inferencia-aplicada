"""The write-side result contract every domain's raw write tools return.

See `docs/solution-docs/04-contracts.md` §1, R3 and ADR-027. `ActionResult`
lives in `core` (not `cards` or `disputes`) because both domains return it and
neither can import the other, and `conversation` can't be imported from
outside itself (`06` §2). This module imports no `app.domains` module.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

__all__ = ["ActionResult", "ReadbackValue"]

ReadbackValue = str | int | bool | Decimal | date | datetime | None
"""One field of `ActionResult.readback`, formatted in code (R4), never by the LLM."""


class ActionResult(BaseModel):
    """What a confirmed write returns, and what `TurnState.actions` accumulates.

    `verified` has no default (R3): a caller that forgets to re-read the
    record after a write fails validation instead of silently reporting
    "done". `audit_event_id` stays `None` until audit logging lands (D3-A5).
    `tracking_id` is set only by `order_replacement`. `case_ids` is set only
    by `disputes.create_claim` (D4-B D16).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    tool: str
    """Registry name, e.g. `"cards.lock_card"`."""
    status: Literal["applied"]
    verified: bool
    readback: dict[str, ReadbackValue]
    audit_event_id: UUID | None = None
    tracking_id: str | None = None
    case_ids: list[str] | None = None
