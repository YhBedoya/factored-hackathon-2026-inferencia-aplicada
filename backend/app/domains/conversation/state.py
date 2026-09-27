"""The turn graph's state. See `docs/solution-docs/02-conversation-design.md` §3.

`TurnState` is a plain `TypedDict` and `bind_once` a plain function: K3 adds
no graph-framework dependency (D-facts, this card). The graph framework
itself will read the `Annotated[..., bind_once]` / `Annotated[..., add]`
metadata once B3 wires this state into a graph.
"""

from datetime import date, datetime
from decimal import Decimal
from operator import add
from typing import Annotated, Any, Literal, NotRequired, TypedDict

from pydantic import BaseModel, ConfigDict

from app.domains.conversation.schemas import Intent, NLUResult, NLUSlots

__all__ = ["Fact", "Pending", "TurnState", "bind_once"]


def bind_once(current: str | None, update: str) -> str:
    """Reducer for `TurnState.customer_id` (D4, R1, ADR-025 "read-only").

    Accepts the first write (`current` is `""` or `None`) and repeats of the
    same value. Any other value means something tried to reassign the
    session's customer mid-conversation, which R1 forbids.
    """
    if current is None or current == "":
        return update
    if update == current:
        return current
    raise ValueError(f"R1: customer_id is write-once; already bound to {current!r}, got {update!r}")


class Pending(TypedDict):
    """A flow paused waiting on one slot (`02` §3)."""

    flow: str
    node: str
    awaiting_slot: str | None


class Fact(BaseModel):
    """A composer-ready fact with its provenance (D5, `02` §4.2)."""

    model_config = ConfigDict(frozen=True)

    key: str
    value: str | int | Decimal | date | datetime | None
    source: str


class TurnState(TypedDict):
    """Checkpointed graph state, keyed by `conversation_id` (`02` §3, D3)."""

    customer_id: Annotated[str, bind_once]
    language: NotRequired[Literal["es", "pt"]]
    country: NotRequired[Literal["MX", "CO", "AR"]]
    mode: NotRequired[Literal["bot", "human"]]
    nlu: NotRequired[NLUResult | None]
    intent_queue: NotRequired[list[Intent]]
    pending: NotRequired[Pending | None]
    slots: NotRequired[NLUSlots]
    selected_card_id: NotRequired[str | None]
    clarification_failures: NotRequired[int]
    confirmation_token_id: NotRequired[str | None]
    facts: NotRequired[Annotated[list[Fact], add]]
    actions: NotRequired[Annotated[list[dict[str, Any]], add]]
    escalation_reason: NotRequired[str | None]
