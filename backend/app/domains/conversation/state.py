"""The turn graph's state. See `docs/solution-docs/02-conversation-design.md` §3.

`TurnState` is a plain `TypedDict` and `bind_once` a plain function: K3 adds
no graph-framework dependency (D-facts, this card). The graph framework
itself will read the `Annotated[..., bind_once]` / `Annotated[..., add]`
metadata once B3 wires this state into a graph.

B3 (D1-B, `docs/plans/d1-b-agent-sandbox.md` Q3) changes `facts`'s reducer
from a plain `operator.add` append to "append, or reset on a marker": see
`RESET_FACTS` below. This is the one K3 field this card touches; Dev A
reviews the change.
"""

from datetime import date, datetime
from decimal import Decimal
from operator import add
from typing import Annotated, Literal, NotRequired, TypedDict

from pydantic import BaseModel, ConfigDict

from app.core.actions import ActionResult
from app.domains.conversation.schemas import Intent, NLUResult, NLUSlots

__all__ = ["RESET_FACTS", "Fact", "Pending", "TurnState", "bind_once"]


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
    """A flow paused waiting on one slot (`02` §3).

    `awaiting_slot` names the slot outside `slots` that a resume fills.
    `"confirmation"` (D15) waits on `TurnInput.confirmation` or an NLU
    affirm/deny against an issued plan; `"otp"` (D15, ADR-027) waits on
    step-up completing before a plan can even be issued. The type stays
    `str | None` so a flow's own domain slots (e.g. `"card_id"`) keep working.
    """

    flow: str
    node: str
    awaiting_slot: str | None


class Fact(BaseModel):
    """A composer-ready fact with its provenance (D5, `02` §4.2)."""

    model_config = ConfigDict(frozen=True)

    key: str
    value: str | int | Decimal | date | datetime | None
    source: str


class _FactsReset(list[Fact]):
    """Marker subclass for `TurnState.facts` (Q3).

    An instance of this class means "start this turn's facts over", not
    "append these facts". `_reduce_facts` tells the two apart with
    `isinstance`, so any plain `list[Fact]` (including an empty one built by
    hand) still appends.
    """


RESET_FACTS: list[Fact] = _FactsReset()
"""The single marker instance flows/nodes write to reset `facts` (Q3).

`load_session` writes this at the start of every turn so a later `compose`
node sees only facts a flow wrote *this* turn (the K3 open question on
`facts` accumulating across turns). Every other write to `facts` is a plain
`list[Fact]` and appends, same as the old `operator.add` reducer.
"""


def _reduce_facts(current: list[Fact], update: list[Fact]) -> list[Fact]:
    """Reducer for `TurnState.facts`: reset on `RESET_FACTS`, else append (Q3)."""
    if isinstance(update, _FactsReset):
        return []
    return current + update


class TurnState(TypedDict):
    """Checkpointed graph state, keyed by `conversation_id` (`02` §3, D3)."""

    customer_id: Annotated[str, bind_once]
    language: NotRequired[Literal["es", "pt"]]
    country: NotRequired[Literal["MX", "CO", "AR"]]
    # The customer's first name as registered (PII). Written only by
    # `load_session` from `customers.get_profile`; the LLM sees it only as
    # the `{customer_name}` placeholder key, filled in code (R5).
    customer_name: NotRequired[str | None]
    mode: NotRequired[Literal["bot", "human"]]
    nlu: NotRequired[NLUResult | None]
    intent_queue: NotRequired[list[Intent]]
    pending: NotRequired[Pending | None]
    slots: NotRequired[NLUSlots]
    selected_card_id: NotRequired[str | None]
    clarification_failures: NotRequired[int]
    confirmation_token_id: NotRequired[str | None]
    facts: NotRequired[Annotated[list[Fact], _reduce_facts]]
    actions: NotRequired[Annotated[list[ActionResult], add]]
    escalation_reason: NotRequired[str | None]
