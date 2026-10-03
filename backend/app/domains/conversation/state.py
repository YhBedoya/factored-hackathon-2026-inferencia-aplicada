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
from typing import Annotated, Any, Literal, NotRequired, TypedDict

from pydantic import BaseModel, ConfigDict

from app.core.actions import ActionResult
from app.domains.conversation.schemas import Intent, NLUResult, NLUSlots
from app.domains.handoff.schemas import HandoffEvidence
from app.domains.localization.format import Queue

__all__ = [
    "RESET_FACTS",
    "RESET_INTENT_SEGMENTS",
    "RESET_SEGMENTS",
    "DeclineState",
    "DisputeState",
    "Fact",
    "HistoryMessage",
    "IntentSegment",
    "Pending",
    "TurnState",
    "TxOfferState",
    "bind_once",
    "mark_segment",
]


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


class HistoryMessage(TypedDict):
    """One masked message of the conversation window (naturalidad-cardy D3, R5).

    `text` is `user_text` or the masked reply, never raw PII.
    """

    role: Literal["customer", "cardy"]
    text: str


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


class _SegmentsReset(list[str]):
    """Marker subclass for `GraphState.segments` (B3), same pattern as
    `_FactsReset` above: an instance means "start this turn's segments
    over", not "append these segments". `_reduce_segments` tells the two
    apart with `isinstance`, so any plain `list[str]` still appends.

    `segments` itself is declared on `graph.py`'s `GraphState`, not on
    `TurnState` below (it is graph-local, not checkpointed domain state), but
    its reducer lives here rather than in `graph.py`: `graph.py` also runs as
    `__main__` for `python -m ... --mermaid` (D19), and a reducer function
    defined there would then exist as two distinct objects -- one per module
    identity -- so `StateGraph.add_node` would see `segments` "already exist
    with a different type" the moment a node module imports `GraphState` by
    its normal package path. `state.py` is never run as `__main__`, so it
    stays the one place a reducer used across both import paths is safe.
    """


RESET_SEGMENTS: list[str] = _SegmentsReset()
"""The marker `load_session` writes every turn so `finish` only ever joins
the segments a node wrote *this* turn (same reasoning as `RESET_FACTS`).
"""


def _reduce_segments(current: list[str], update: list[str]) -> list[str]:
    """Reducer for `GraphState.segments`: reset on `RESET_SEGMENTS`, else append (B3)."""
    if isinstance(update, _SegmentsReset):
        return []
    return current + update


SegmentStatus = Literal["resolved", "awaiting", "handoff", "abstained", "cancelled"]


class IntentSegment(TypedDict):
    """What one turn did for one real intent (analytics spec D2, D14, D17, D22).

    It is the `segments` entry of the `reply_sent` audit payload. `awaiting_slot`
    is present only on `awaiting` and `bot_offered` only on a flow the bot
    itself offered, so the audit JSON stays small.
    """

    intent: str
    route: str
    status: SegmentStatus
    awaiting_slot: NotRequired[str]
    bot_offered: NotRequired[bool]


class _IntentSegmentsReset(list[IntentSegment]):
    """Marker subclass for `GraphState.intent_segments`, same pattern as
    `_SegmentsReset`: an instance means "start this turn's record over".
    The reducer lives here for the same `__main__` reason (see above).
    """


RESET_INTENT_SEGMENTS: list[IntentSegment] = _IntentSegmentsReset()
"""Written by `load_session` every turn so the runner only reads this turn's segments."""


def _reduce_intent_segments(
    current: list[IntentSegment], update: list[IntentSegment]
) -> list[IntentSegment]:
    """Reducer for `GraphState.intent_segments`: reset on the marker, else append (D14)."""
    if isinstance(update, _IntentSegmentsReset):
        return []
    return current + update


def mark_segment(status: SegmentStatus, *, awaiting_slot: str | None = None) -> dict[str, Any]:
    """A flow's explicit say on how it ended, for the segment wrapper (`graph.py`).

    The node merges the returned dict into its update. The wrapper removes
    `segment_mark` before LangGraph sees it, so it is never a channel. Flows
    use it only for endings the wrapper cannot infer from the update (D18).
    """
    mark: dict[str, Any] = {"status": status}
    if awaiting_slot is not None:
        mark["awaiting_slot"] = awaiting_slot
    return {"segment_mark": mark}


class DisputeState(TypedDict):
    """`unrecognized_charge`'s own sub-state (D4-B §Contracts "Graph and state").

    `card_id` is the card the candidates were pulled from; `offered_tx_ids`
    and `fraud_scores` are what `ui.transaction_list` showed (`fraud_scores`
    keyed by `tx_id`, so the flow never re-reads the bank to compute the
    compromise rule on a resume). `picked_tx_ids` and `answers` accumulate
    across the pick and the question turns; `question_index` is where
    `policies/disputes.yaml`'s `questions` list resumes on the single-charge
    path. `compromise` and `block_refused` are read back by the plan's own
    "confirm" resume to tell the two-step compromise plan, the claim-only
    plan issued after a refused block (D10), and the single-charge one-step
    plan apart -- they otherwise share the same `pending.node`.
    """

    card_id: str
    offered_tx_ids: list[str]
    fraud_scores: dict[str, Decimal | None]
    picked_tx_ids: list[str]
    answers: list[str]
    question_index: int
    compromise: bool
    block_refused: bool


class DeclineState(TypedDict):
    """`decline_explain`'s own sub-state (this card's B1, `02` §4.3 D2-D3).

    `card_id` is the card the offered declines were pulled from;
    `offered_tx_ids` is what the single-pick `ui.transaction_list` showed.
    Unlike `DisputeState`, there is no accumulation across turns -- the pick
    is the flow's only pause, so nothing here survives past the resume that
    explains one of the offered declines.
    """

    card_id: str
    offered_tx_ids: list[str]


class TxOfferState(TypedDict):
    """`tx_search`/`tx_explain`'s own sub-state (this card's B1, `02` §4.4/§4.5
    D1/D3).

    Both flows share one shape: `flow` tells a resume which of the two is
    paused (they reuse the same `awaiting_slot = "transactions"`), and
    `offered_tx_ids` is what the single-pick `ui.transaction_list` showed --
    the same "re-check the pick is exactly one offered id" use as
    `DeclineState.offered_tx_ids`.
    """

    flow: Literal["tx_search", "tx_explain"]
    offered_tx_ids: list[str]


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
    dispute: NotRequired[DisputeState | None]
    decline: NotRequired[DeclineState | None]
    # Handoff (D4-A): the queue a flow or rule chose, the created row's id, the
    # count of attempts on another person's data (D6), and the evidence and
    # code-filled open questions the fraud flow attaches to the packet (D4-B
    # D10). All are cleared on return to bot (D14).
    handoff_queue: NotRequired[Queue | None]
    handoff_id: NotRequired[str | None]
    unauthorized_attempts: NotRequired[int]
    handoff_evidence: NotRequired[list[HandoffEvidence]]
    handoff_open_questions: NotRequired[list[str]]
    # `tx_search`/`tx_explain`'s single-pick offer (this card's B1).
    tx_offer: NotRequired[TxOfferState | None]
    # `unrecognized_charge`'s priority-flag names, sorted (this card's B2,
    # A6-A7): `amount_over_threshold`, `open_critical`, `repeat_complainer`.
    # Read by `nodes/handoff.py` to append `priority_claim` to
    # `escalation_rules_hit`, then cleared on handoff.
    priority_flags: NotRequired[list[str]]
    # Conversation memory (naturalidad-cardy D3): the last 6 masked messages and
    # an LLM-written masked summary of the older ones. Plain last-write-wins.
    history: NotRequired[list[HistoryMessage]]
    summary: NotRequired[str | None]
    # The flow a bot offer opened (`replacement` after a permanent block), kept
    # while that flow is paused so its later turns still carry `bot_offered`
    # (analytics D22). Written only by the segment wrapper in `graph.py`.
    bot_offered_flow: NotRequired[str | None]
