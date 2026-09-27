"""The session-bound context tools are built from.

See `docs/solution-docs/04-contracts.md` §1. The registry builds `ToolContext`
from the session; no route, tool or prompt ever constructs one from
LLM-supplied input (R1, D2).
"""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

__all__ = ["ToolContext"]


class ToolContext(BaseModel):
    """Built by the registry, never by the model. See `04` §1 (D17)."""

    model_config = ConfigDict(frozen=True)

    customer_id: str
    conversation_id: UUID
    actor: Literal["customer", "agent", "system"]
    trace_id: str
    policy_version: str
