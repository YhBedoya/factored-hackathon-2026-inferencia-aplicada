"""The v0 turn graph: I/O channels, `build_graph`, `run_turn`, `DebugInfo` (D8, Q2).

`TurnInput`/`TurnOutput` are this graph's own channels, not part of the K3
`TurnState` contract (`docs/plans/d1-b-agent-sandbox.md` Q2): `user_text` is
what the sandbox writes in before a turn runs, `reply` is what it reads out
once `finish` runs. `GraphState` is `TurnState` plus both, with
`user_text`/`reply` re-declared `NotRequired` here (they are required in
their own `TypedDict`s) so a node's partial-update return dict never has to
restate keys it did not touch.

B3 (this card) turns the old three-terminal-node shape into a real turn
loop, so one turn can answer several queued intents in one reply:

* `segments` is a graph-local channel (not checkpointed `TurnState`, same as
  `ui`): every reply-writing node appends its filled template to it instead
  of setting `reply` directly. `RESET_SEGMENTS` (`state.py`'s `_SegmentsReset`
  marker, same pattern as `RESET_FACTS`) is what `load_session` writes every
  turn so a later `finish` never sees a stale segment from an earlier one.
  Its reducer lives in `state.py`, not here, even though `segments` itself is
  declared below: `graph.py` also runs as `__main__` for the mermaid CLI
  (D19), and a reducer defined in a module that gets loaded twice under two
  identities would make `GraphState`'s "segments" channel compare unequal to
  itself the moment a node module imports `GraphState` by its normal package
  path (`StateGraph.add_node` then raises "already exists with a different
  type"). `state.py` is never run as `__main__`, so it stays the one safe
  place for a reducer any node module and this file's own `__main__` run
  both need to agree on.
* `resume` is the button/step-up counterpart to `TurnInput.confirmation`:
  `"step_up"` means the customer just completed OTP outside the graph and
  this turn should try to resume whatever was waiting on it;
  `"step_up_cancel"` (S2) is the customer's Cancel on any OTP pause: the agent pause goes to
  `agent_step_up`, the pipeline pause to `otp_cancel`.
* `_entry` (after `load_session`), `route` (after `understand`), `enqueue`,
  `_dispatch`, `_after_flow` and `_after_segment` are this turn's routing
  decisions (`docs/plans/d2-b-card-info-block.md` §"Graph shape"). `route`
  itself lives in `nodes/route.py`; the rest stay here, next to the mapping
  tables they read (`_INTENT_NODES`, `_FLOW_NODES`), because those tables
  are this graph's shape, not one node's private detail. Flow tasks add
  their own node to both tables (and to `_BRANCH_NODES`) without touching
  this routing logic again.
* `enqueue` and `next_intent` (`nodes/next_intent.py`) turn this turn's
  intents into a queue and walk it one flow at a time, resetting `facts`
  between two different intents' turns at the wheel (Q3) so `compose`
  never blends one intent's facts into another's segment.
* `finish` joins `segments` into the single `reply` output channel and ends
  the turn (`nodes/next_intent.py`).

`build_graph` imports the node modules inside its own body, rather than at
module level -- importing them at the top would be a cycle, since every node
module imports `GraphState`/`TurnInput`/`TurnOutput` from here.

`run_turn` drives one turn end to end and assembles the sandbox's debug line
(`07` §1): the reply from the `reply` output channel (written only by
`finish`), the route from the first of `_BRANCH_NODES` seen in the
`astream` update sequence (never `enqueue`/`next_intent`/`finish`, which are
plumbing, not a routing decision), `tools_called` from whatever the
caller's `bank_tools` records on itself, `pending` from the final
checkpointed state (`graph.aget_state`, since a paused turn's last node may
not be the one that set `pending`) and `ui` from the last `ui` value any
node wrote this turn.
"""

import functools
import sys
from collections.abc import Awaitable, Callable
from typing import Annotated, Any, Literal, NotRequired, TypedDict, cast, get_args

import structlog
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.errors import AccessDenied
from app.domains.audit.schemas import NullAuditRecorder
from app.domains.conversation.fact_values import record
from app.domains.conversation.intent_registry import intent_nodes, management_intents
from app.domains.conversation.schemas import Intent, NLUResult, NLUSlots, NLUStatus
from app.domains.conversation.state import (
    HistoryMessage,
    IntentSegment,
    SegmentStatus,
    TurnState,
    _reduce_intent_segments,
    _reduce_segments,
    mark_segment,
)
from app.domains.conversation.templates import get_template
from app.domains.conversation.ui import UIEvent
from app.domains.handoff.schemas import HandoffReason
from app.domains.policy.escalation import legal_hit, rule_queue
from app.domains.policy.registry import get_policies

__all__ = [
    "CardSelection",
    "ConfirmationDecision",
    "DebugInfo",
    "GraphState",
    "TurnInput",
    "TurnOutput",
    "TxSelection",
    "build_graph",
    "run_turn",
]


class TxSelection(BaseModel):
    """The pick step's input: which offered transactions the customer chose
    (D4-B D7, `04` §3 selection body). It sits next to `ConfirmationDecision`
    because the API imports both from here (D7). `tx_ids` are checked against
    `dispute.offered_tx_ids` by the route (`409 selection_invalid`) and again
    by the flow -- this model only enforces the input's own shape: 1-10 ids,
    no duplicate.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    tx_ids: list[str] = Field(min_length=1, max_length=10)

    @field_validator("tx_ids")
    @classmethod
    def _unique(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("tx_ids must be unique")
        return value


class CardSelection(BaseModel):
    """The replacement picker's input: which cards the customer chose to replace.

    Empty is allowed ("none of these"). The route checks the ids against the
    offered ones (`409 selection_invalid`) and the flow checks them again; this
    model only enforces the input's own shape: at most 10 ids, no duplicate.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    card_ids: list[str] = Field(max_length=10)

    @field_validator("card_ids")
    @classmethod
    def _unique(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("card_ids must be unique")
        return value


class ConfirmationDecision(BaseModel):
    """The button-resume input for a paused plan (D17, `04` §3).

    `token_id` must match `TurnState.confirmation_token_id` for the resume to
    execute anything; a stale or mismatched token is a no-op (B5 checks it).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    token_id: str
    decision: Literal["confirm", "cancel"]


class TurnInput(TypedDict):
    """One turn's raw input channel: the sandbox's user message (Q2).

    `confirmation` is the button-resume path (D17): every caller passes it
    explicitly (`None` on a typed turn) so a checkpointed value never leaks
    into the next turn, and when it is set the turn skips `understand` (no
    LLM call; `_entry` is the routing that does the skipping). `resume`
    (D8, D20) is the same idea for the OTP path: `"step_up"` means step-up
    just completed outside the graph, and this turn should try to resume
    whatever paused on it; `"step_up_cancel"` (S2) is Cancel on any OTP pause (the agent
    pause goes to `agent_step_up`, the pipeline pause to `otp_cancel`). `selection`
    (D4-B D7) is the same shape again
    for `unrecognized_charge`'s pick step: every caller passes it explicitly
    (`None` otherwise), and when it is set (and the checkpoint is actually
    paused on it) `_entry` skips `understand` too -- the pick is never run
    through NLU, and never saved as a customer message. `card_selection` is the
    same again for the replacement picker: passed explicitly every turn (`None`
    otherwise), never run through NLU.
    """

    user_text: str
    confirmation: NotRequired[ConfirmationDecision | None]
    resume: NotRequired[Literal["step_up", "step_up_cancel", "step_up_failed"] | None]
    selection: NotRequired[TxSelection | None]
    card_selection: NotRequired[CardSelection | None]
    introduced: NotRequired[bool]
    history: NotRequired[list[HistoryMessage]]


class TurnOutput(TypedDict):
    """One turn's raw output channel: the composed reply (Q2) and UI events.

    `ui` (D16) is this turn's push events for the frontend (`ui.py`) -- a
    confirmation card, an OTP prompt, and so on -- appended by whichever flow
    node paused or resumed.
    """

    reply: str
    ui: NotRequired[list[UIEvent]]


class GraphState(TurnState):
    """The compiled graph's state: `TurnState` plus this turn's I/O (D8).

    Mypy (PEP 655) refuses to let a subclass re-declare an inherited
    *required* `TypedDict` field as `NotRequired` -- confirmed against this
    repo's mypy config, not assumed -- so `user_text`/`reply` are declared
    fresh here rather than through `(TurnState, TurnInput, TurnOutput)`
    multiple inheritance. `TurnInput`/`TurnOutput` stay the graph's actual
    input/output schema (required, for `build_graph` to pass to
    `StateGraph`); only this internal, per-node state loosens them, so a
    node's partial-update return dict never has to restate a key it did not
    touch.

    `segments`, `grounding` and `resume` are graph-local, not part of the checkpointed
    `TurnState` contract (B3): a flow's filled reply text and this turn's
    step-up resume flag are this graph's own bookkeeping, not something a
    tool, a policy or another domain ever reads.

    `intent_segments` (analytics D14) is the per-intent record of the turn
    and is a different thing from `segments` (the reply texts). Only
    `_track_segments` writes it. `segment_deferred` holds a read flow's
    segment until `compose` has run, because a compose failure turns it into
    a `handoff` (D2).
    """

    user_text: NotRequired[str]
    reply: NotRequired[str]
    confirmation: NotRequired[ConfirmationDecision | None]
    resume: NotRequired[Literal["step_up", "step_up_cancel", "step_up_failed"] | None]
    selection: NotRequired[TxSelection | None]
    card_selection: NotRequired[CardSelection | None]
    ui: NotRequired[list[UIEvent]]
    segments: NotRequired[Annotated[list[str], _reduce_segments]]
    intent_segments: NotRequired[Annotated[list[IntentSegment], _reduce_intent_segments]]
    segment_deferred: NotRequired[IntentSegment | None]
    handoff_request: NotRequired[str]
    grounding: NotRequired[str]
    actions_at_turn_start: NotRequired[int]
    write_failed: NotRequired[bool]
    degraded: NotRequired[bool]
    # personalidad-cardy D6: "sí" to the closing suggestion this turn. Reset by
    # `load_session`, set by `enqueue`, read only by `tx_search` as a criterion.
    suggestion_accepted: NotRequired[bool]
    # s0-empty-reply: per-turn, reset by `load_session`. `asked_ui` is the asking
    # flow node's own events when it wrote a flow-question `pending` this turn
    # (None: none did); `non_answer_counted` is set by `_keep_open_question` so
    # `finish` doesn't reset `non_answer_failures` on that turn. Never checkpointed state.
    asked_ui: NotRequired[list[UIEvent] | None]
    non_answer_counted: NotRequired[bool]
    # S1 agent: per-turn, reset by `load_session`, never checkpointed state.
    # `agent_enabled` is the flag as read this turn; `agent_labels` is the agent
    # turn's `{language, status, intents, route}` for the runner's audit;
    # `agent_code_text` is code text that replaces Cardy's reply.
    agent_enabled: NotRequired[bool]
    agent_labels: NotRequired[dict[str, Any] | None]
    agent_code_text: NotRequired[str | None]
    # Written with `agent_code_text` by `agent_plan`; read only on that same turn.
    agent_plan_result: NotRequired[dict[str, Any] | None]
    # Written by `agent_plan` on a verified Acepto turn, read and cleared by the agent
    # node; only meaningful when `agent_code_text` is set. Not reset in `load_session`.
    agent_offer: NotRequired[dict[str, Any] | None]


class DebugInfo(BaseModel):
    """The sandbox's per-turn debug line fields (`07` §1, §"Contracts")."""

    model_config = ConfigDict(frozen=True)

    language: Literal["es", "pt"]
    status: NLUStatus | None
    intents: list[Intent]
    slots: NLUSlots
    route: str
    tools_called: list[str]
    pending: str | None
    ui: list[str]
    degraded: bool = False


_BRANCH_NODES = (
    "card_info",
    "card_block",
    "card_unlock",
    "replacement",
    "unrecognized_charge",
    "decline_explain",
    "tx_search",
    "tx_explain",
    "unsupported",
    "fallback",
    "smalltalk",
    "abstain",
    "handoff_summary",
    "relay_to_agent",
    "agent",
)

_MANAGEMENT_INTENTS: frozenset[Intent] = cast("frozenset[Intent]", management_intents())
"""Conversation-management intents (`02` §1): they never start or continue a
flow on their own, so `route` sends a turn made only of these to `smalltalk`,
and `enqueue` (P1, D20) strips them out of the intent queue.
"""

_INTENT_NODES: dict[Intent, str] = cast("dict[Intent, str]", intent_nodes())
"""Intent -> flow node, read by `_dispatch` (D20, P3). An intent with no
entry here (every Stretch intent, and every card-action intent this card
doesn't ship a flow for yet) falls through to `unsupported`'s fixed
`unsupported_intent` template. Flow tasks add their own entry here.
"""

_FLOW_NODES: dict[str, str] = {
    "card_info": "card_info",
    "card_block": "card_block",
    "card_unlock": "card_unlock",
    "replacement": "replacement",
    "unrecognized_charge": "unrecognized_charge",
    "decline_explain": "decline_explain",
    "tx_search": "tx_search",
    "tx_explain": "tx_explain",
}
"""`Pending.flow` -> flow node, read by `_entry` and `route` (D15, D17,
D20). An unregistered flow name falls through to `unsupported`/`smalltalk`
rather than crashing (P3). Flow tasks add their own entry here.
"""


_FAILURE_REASONS = frozenset({"tool_failure", "llm_unavailable"})
"""`escalation_reason` values that end in `fallback` -> `handoff_summary` -> `handoff` (D8)."""


def _entry(state: GraphState) -> str:
    """Conditional edge right after `load_session` (D8, D15, D17, `02` §3, D4-B D7).

    A conversation in human mode goes to `relay_to_agent` before any other
    check (D7): the bot stays silent while an agent owns the conversation.
    Then the kill switch's failure reason (D10) beats everything else.

    With `AGENT_ENABLED` on, `_routes_to_agent` decides the rest (S1 D6, D7):
    a typed turn it accepts goes to `summarize` and on to `agent`, and a pick on
    a list the agent offered goes straight to `agent`. Everything else is
    `_pipeline_entry`, where a button or step-up with no pipeline pause open is
    `smalltalk`'s stale click: no LLM runs on a turn without text.
    """
    if state.get("mode") == "human":
        return "relay_to_agent"
    otp_pause = _otp_pause(state)
    resume = state.get("resume")
    if resume == "step_up_failed" and otp_pause is not None:
        return "step_up_failed"
    if resume == "step_up_cancel" and otp_pause == "pipeline":
        return "otp_cancel"
    pause = _agent_pause(state)
    if pause == "otp":
        return "agent_step_up"
    if pause is None and _flag_off_address_pause(state):
        # Kill switch with the address question open: the typed address must not reach
        # the NLU (R5), so a code node vaults and drops it (S2 D11).
        pause = "address"
    if (
        pause == "address"
        and state.get("user_text")
        and state.get("confirmation") is None
        and state.get("resume") is None
        and state.get("selection") is None
        and state.get("card_selection") is None
    ):
        return "agent_address"
    if state.get("escalation_reason") == "llm_unavailable":
        return "fallback"
    if _agent_plan_click(state):
        return "agent_plan"
    if _routes_to_agent(state):
        return "agent" if state.get("selection") is not None else "summarize"
    return _pipeline_entry(state)


def _agent_pause(state: GraphState) -> Literal["otp", "address"] | None:
    """Which agent code-node pause is open (S2 D15): the OTP pause or the address
    question. Flag off, nothing (S1 D27)."""
    pending = state.get("pending")
    if not state.get("agent_enabled") or pending is None or pending["flow"] != "agent":
        return None
    if pending["awaiting_slot"] == "otp":
        return "otp"
    if pending["awaiting_slot"] == "address":
        return "address"
    return None


def _otp_pause(state: GraphState) -> Literal["agent", "pipeline"] | None:
    """Who owns the open OTP pause (S2 D28, D30): `agent` (only with the flag on, S1
    D27), `pipeline`, or None when no OTP pause is open."""
    pending = state.get("pending")
    if pending is None or pending["awaiting_slot"] != "otp":
        return None
    if pending["flow"] == "agent":
        return "agent" if state.get("agent_enabled") else None
    return "pipeline"


def _flag_off_address_pause(state: GraphState) -> bool:
    """`AGENT_ENABLED` is off but the agent's address question is still open."""
    pending = state.get("pending")
    return (
        not state.get("agent_enabled")
        and pending is not None
        and pending["flow"] == "agent"
        and pending["awaiting_slot"] == "address"
    )


def _agent_plan_click(state: GraphState) -> bool:
    """A button decision while an agent plan is open (S1 D12): only a click reaches
    `agent_plan`; a typed "si" goes to the agent like any text."""
    pending = state.get("pending")
    return bool(
        state.get("agent_enabled")
        and state.get("confirmation") is not None
        and pending is not None
        and pending["flow"] == "agent"
        and pending["awaiting_slot"] == "confirmation"
    )


def _legal_hit(state: GraphState) -> bool:
    return legal_hit(state.get("user_text", ""), get_policies().escalation)


def _pipeline_question(state: GraphState) -> bool:
    """A flow question a pipeline flow left open (S0 D1): not the agent's pause and
    not the `anything_else` closing."""
    pending = state.get("pending")
    return (
        pending is not None
        and pending["flow"] != "agent"
        and pending["awaiting_slot"] != "anything_else"
    )


def _routes_to_agent(state: GraphState) -> bool:
    """True when this turn is the agent's (S1 D6, D7; `02` §3 routing table).

    Not with the flag off, on a degraded turn (`LLM_DISABLED` never enters the
    agent, D4), on a legal keyword (today's handoff path), or while a pipeline
    flow's question is open (every later turn skips the agent, D7). A pick
    counts only on the list the agent offered; a button or a step-up resume
    never does yet.
    """
    if not state.get("agent_enabled") or state.get("degraded"):
        return False
    if _legal_hit(state) or _pipeline_question(state):
        return False
    if state.get("selection") is not None:
        pending = state.get("pending")
        return (
            pending is not None
            and pending["flow"] == "agent"
            and pending["awaiting_slot"] == "transactions"
        )
    if state.get("confirmation") is not None or state.get("resume") is not None:
        return False
    return bool(state.get("user_text"))


def _pipeline_entry(state: GraphState) -> str:
    """Today's routing after the human-mode and kill-switch checks.

    Four of this turn's shapes skip `understand` entirely (no LLM call): a
    transaction pick, a button confirmation, a step-up resume, and (once a
    flow ships one) a raw address reply. Each continues straight into its
    flow's own node only when it actually matches the open pause; anything
    else is `smalltalk`'s job (a stale button, a resume with no OTP pause
    open, a pick with no list open). Everything else is a fresh turn's text,
    so it goes to `understand`. The pick is checked first (step 0): it is
    its own turn shape, never combined with a confirmation or a step-up
    resume. `_FLOW_NODES[pending["flow"]]` (D5-B, generalized from a
    hard-coded `unrecognized_charge`) is what lets `decline_explain`'s own
    single-pick share this same routing.

    S1 D27: a pause the agent left (`flow: "agent"`) is no pause here, so with
    the flag off (or a turn the agent does not take) a button or pick is a
    stale click and a typed message goes to `understand`.

    Replacement picker: a `card_selection` with the `replacement_cards` pause
    open goes to that flow's node, any other one is `smalltalk`'s (stale). A
    typed turn at that pause also goes to the flow node (it re-sends the offer
    and keeps the pause; no LLM call).
    """
    pending = state.get("pending")
    if pending is not None and pending["flow"] == "agent":
        pending = None
    awaiting_cards = pending is not None and pending["awaiting_slot"] == "replacement_cards"
    if state.get("card_selection") is not None:
        if pending is not None and awaiting_cards:
            return _FLOW_NODES[pending["flow"]]
        return "smalltalk"
    selection = state.get("selection")
    if selection is not None:
        if pending is not None and pending["awaiting_slot"] == "transactions":
            return _FLOW_NODES[pending["flow"]]
        return "smalltalk"
    confirmation = state.get("confirmation")
    if confirmation is not None:
        if pending is not None and pending["awaiting_slot"] == "confirmation":
            return _FLOW_NODES[pending["flow"]]
        return "smalltalk"
    if state.get("resume") == "step_up":
        if pending is not None and pending["awaiting_slot"] == "otp":
            return _FLOW_NODES[pending["flow"]]
        return "smalltalk"
    if pending is not None and pending["awaiting_slot"] == "address":
        return _FLOW_NODES[pending["flow"]]
    if pending is not None and awaiting_cards:
        return _FLOW_NODES[pending["flow"]]
    return "understand"


def _after_summarize(state: GraphState) -> str:
    """Conditional edge after `summarize`: the agent when `_routes_to_agent` says so,
    else `understand`, exactly as the plain edge did."""
    return "agent" if _routes_to_agent(state) else "understand"


def _after_agent(state: GraphState) -> str:
    """Conditional edge after `agent` (S1 D3, D4, D7, R11): a handoff reason goes to
    `handoff_summary`, a tool failure to `fallback`; a reply (a segment) ends the
    turn; no reply is a passed turn or a degraded one, and the pipeline takes it.
    """
    reason = state.get("escalation_reason")
    if reason == "agent_round_cap" or state.get("handoff_queue") is not None:
        return "handoff_summary"
    if reason in _FAILURE_REASONS:
        return "fallback"
    return "finish" if state.get("segments") else "understand"


def _after_agent_plan(state: GraphState) -> str:
    """Conditional edge after `agent_plan` (S1 D14, D15): a failed step is a handoff
    (or a tool failure) exactly as a flow's; otherwise the agent words the result,
    and a stale click just ends the turn with the reminder and the card."""
    reason = state.get("escalation_reason")
    if reason in _FAILURE_REASONS:
        return "fallback"
    if reason is not None or state.get("handoff_queue") is not None:
        return "handoff_summary"
    return "agent" if state.get("agent_code_text") is not None else "finish"


def _after_agent_pause(state: GraphState) -> str:
    """Conditional edge after `agent_step_up` / `agent_address` (S2 D17): as
    `_after_agent_plan`; `agent_address` never sets `agent_code_text`."""
    return _after_agent_plan(state)


def _dispatch(state: GraphState) -> str:
    """Conditional edge shared by `enqueue` and `next_intent` (D8, D20): the
    queue's head decides the flow node through `_INTENT_NODES`; an empty
    queue (nothing left to answer) ends the turn at `finish`.
    """
    # ADR-032 D7: an LLM failure on a degraded turn ends in the fixed fallback.
    if state.get("escalation_reason") == "llm_unavailable":
        return "fallback"
    queue = state.get("intent_queue") or []
    if not queue:
        return "finish"
    return _INTENT_NODES.get(queue[0], "unsupported")


def _after_flow(state: GraphState) -> str:
    """Conditional edge after a flow node (D8, D15): a handoff reason (or a
    queue a flow chose) goes to `handoff_summary`; an escalation reason
    with no card left to talk about goes to the fixed-template `fallback`;
    non-empty `facts` goes to `compose`. A flow that already answered with
    its own fixed template (no facts, e.g. a future `already_in_state`)
    falls straight into `_after_segment`'s own decision instead of a third,
    redundant node.
    """
    reason = state.get("escalation_reason")
    # D8: a failure reason is not a HandoffReason by itself here -- it first
    # gets its fixed failure text from `fallback`, which then hands off.
    if reason in _FAILURE_REASONS or reason == "no_cards":
        return "fallback"
    if reason in get_args(HandoffReason) or state.get("handoff_queue") is not None:
        return "handoff_summary"
    if state.get("facts"):
        return "compose"
    return _after_segment(state)


def _after_segment(state: GraphState) -> str:
    """Conditional edge after `compose`, `fallback`, `unsupported` and any
    flow that answered with a fixed template only (D8, D20): a pause ends
    the turn right where it is -- `next_intent` would wrongly move on to the
    next queued intent before this one is resolved -- and the queue stays
    put for the resume that answers it.
    """
    return "finish" if state.get("pending") is not None else "next_intent"


def _after_compose(state: GraphState) -> str:
    """Conditional edge after `compose` (D8): an `LLMError` from its own call
    wrote no segment and set a failure reason, so `fallback` speaks instead.
    """
    if state.get("escalation_reason") in _FAILURE_REASONS:
        return "fallback"
    return _after_segment(state)


def _after_fallback(state: GraphState) -> str:
    """Conditional edge after `fallback` (D8): the two failure reasons hand off."""
    if state.get("escalation_reason") in _FAILURE_REASONS:
        return "handoff_summary"
    return _after_segment(state)


def _after_unsupported(state: GraphState) -> str:
    """Conditional edge after `unsupported` (D6): the attempt that reaches the
    threshold set `unauthorized_access` and no segment, so it hands off.
    """
    if state.get("escalation_reason") == "unauthorized_access":
        return "handoff_summary"
    return _after_segment(state)


def _guard_access[N: Callable[..., Awaitable[dict[str, Any]]]](node: N) -> N:
    """Wrap a flow node so an `AccessDenied` from a tool is a refusal, not a crash (D6).

    Same accounting as `unsupported`'s NLU path: each attempt is audited and
    counted, and the one that reaches the policy threshold hands off.
    """

    @functools.wraps(node)
    async def guarded(state: GraphState, config: RunnableConfig) -> dict[str, Any]:
        try:
            return await node(state, config)
        except AccessDenied:
            attempt = state.get("unauthorized_attempts", 0) + 1
            recorder = config["configurable"].get("audit") or NullAuditRecorder()
            await recorder.record("access_denied", {"source": "tool", "attempt": attempt})
            threshold = get_policies().escalation.unauthorized_access.attempts_before_handoff
            if attempt >= threshold:
                return {
                    "unauthorized_attempts": attempt,
                    "escalation_reason": "unauthorized_access",
                }
            text = get_template("injection_suspected", state.get("language", "es"))
            return {
                "unauthorized_attempts": attempt,
                "segments": [text],
                **mark_segment("abstained"),
            }

    return cast(N, guarded)


def _keep_open_question[N: Callable[..., Awaitable[dict[str, Any]]]](name: str, node: N) -> N:
    """Wrap a flow node: a non-answer on its open question is replayed or handed off.

    A non-answer is an LLM-path turn with no intent that doesn't answer the open
    flow question. The wrapper never calls the node then: the first one replays
    the stored question (`open_question`), the second hands off, cancelling an
    open plan first (R2). Anything else runs the node unchanged; when the node
    opens a flow question, its own `ui` is kept for `finish` to store.
    """

    @functools.wraps(node)
    async def kept(state: GraphState, config: RunnableConfig) -> dict[str, Any]:
        # Imported here: both modules import `GraphState` from this one.
        from app.domains.conversation.flows.actions import handoff
        from app.domains.conversation.nodes.route import _answer_fits

        nlu = state.get("nlu")
        pending = state.get("pending")
        if (
            nlu is not None
            and not state.get("degraded", False)
            and not nlu.intents
            and pending is not None
            and pending["awaiting_slot"] != "anything_else"
            and _FLOW_NODES.get(pending["flow"]) == name
            and not _answer_fits(nlu, pending)
        ):
            new = state.get("non_answer_failures", 0) + 1
            if new == 1:
                replay: dict[str, Any] = {"non_answer_failures": 1, "non_answer_counted": True}
                stored = state.get("open_question")
                if stored is not None:
                    # D16: the replayed sentence is grounded once already; recording
                    # it keeps `reply_sent.fact_values` covering the whole reply.
                    record(stored["text"])
                    replay["segments"] = [stored["text"]]
                    replay["ui"] = list(stored["ui"])
                return replay
            token_id = state.get("confirmation_token_id")
            bank_write_tools = config["configurable"].get("bank_write_tools")
            if token_id is not None and bank_write_tools is not None:
                await bank_write_tools.cancel_plan(token_id)
            return {
                **handoff(
                    rule_queue(get_policies().escalation, "clarification_exhausted"),
                    "clarification_exhausted",
                    state.get("language", "es"),
                ),
                "non_answer_failures": 0,
            }

        update = await node(state, config)
        new_pending = update.get("pending")
        if new_pending is not None and new_pending["awaiting_slot"] != "anything_else":
            return {**update, "asked_ui": list(update.get("ui") or [])}
        return update

    return cast(N, kept)


_logger = structlog.get_logger()

_FLOW_INTENT: dict[str, str] = {}
for _intent, _node in _INTENT_NODES.items():
    _FLOW_INTENT.setdefault(_node, _intent)
"""Flow node -> its registry intent, for a resume whose queue head belongs to
another flow (the replacement offer). `card_info` serves two intents; its
resume always finds its own intent at the queue head, so the first one is only
a fallback.
"""


def _real_intents(state: GraphState) -> list[str]:
    nlu = state.get("nlu")
    return [] if nlu is None else [i for i in nlu.intents if i not in _MANAGEMENT_INTENTS]


def _queue_head(state: GraphState) -> Intent | None:
    queue = state.get("intent_queue") or []
    return queue[0] if queue else None


def _flow_segment(name: str, state: GraphState, update: dict[str, Any]) -> dict[str, Any]:
    """The segment a flow node's turn produced, by D2's first-match rules (D18)."""
    pending = state.get("pending")
    via_pending = pending is not None and _FLOW_NODES.get(pending["flow"]) == name
    head = _queue_head(state)
    if via_pending and (head is None or _INTENT_NODES.get(head) != name):
        intent = _FLOW_INTENT.get(name)
    else:
        intent = head
    if intent is None:
        return {}

    new_pending = update["pending"] if "pending" in update else pending
    owns_pending = new_pending is not None and _FLOW_NODES.get(new_pending["flow"]) == name

    # D22: a pause another flow opened as an offer marks the flow it opened.
    offered = state.get("bot_offered_flow")
    bot_offered = via_pending and offered is not None and _FLOW_NODES.get(offered) == name
    new_offered: str | None = None
    if new_pending is not None and not owns_pending and new_pending["node"] == "offer":
        new_offered = new_pending["flow"]
    elif owns_pending and bot_offered:
        new_offered = offered
    out: dict[str, Any] = {}
    if new_offered != offered:
        out["bot_offered_flow"] = new_offered

    segment: IntentSegment = {"intent": intent, "route": name, "status": "resolved"}
    if bot_offered:
        segment["bot_offered"] = True

    mark = update.get("segment_mark")
    reason = update.get("escalation_reason")
    status: SegmentStatus
    if mark is not None:
        status = mark["status"]
        if mark.get("awaiting_slot") is not None:
            segment["awaiting_slot"] = mark["awaiting_slot"]
    elif reason == "no_cards":
        status = "abstained"
    elif reason is not None or update.get("handoff_queue") is not None:
        status = "handoff"
    elif owns_pending and new_pending is not None:
        status = "awaiting"
        if new_pending["awaiting_slot"] is not None:
            segment["awaiting_slot"] = new_pending["awaiting_slot"]
    elif any(a.verified for a in update.get("actions") or []):
        status = "resolved"
    elif update.get("facts"):
        # Decided after `compose`: a compose failure makes it a handoff.
        out["segment_deferred"] = segment
        return out
    else:
        # A flow ending nobody classified: record nothing rather than guess.
        _logger.warning("segment.unmarked", node=name)
        return out
    segment["status"] = status
    out["intent_segments"] = [segment]
    return out


def _segment_update(name: str, state: GraphState, update: dict[str, Any]) -> dict[str, Any]:
    """The extra channels a wrapped node's update gets (never an LLM's say, R6)."""
    if name in _FLOW_NODES:
        return _flow_segment(name, state, update)
    if name == "unsupported":
        nlu = state.get("nlu")
        head = _queue_head(state)
        # An injection attempt is not work on the paused intent behind it.
        if head is None or (nlu is not None and nlu.status == "injection_suspected"):
            return {}
        return {"intent_segments": [{"intent": head, "route": name, "status": "abstained"}]}
    if name == "abstain":
        return {
            "intent_segments": [
                {"intent": i, "route": name, "status": "abstained"} for i in _real_intents(state)
            ]
        }
    if name == "compose":
        deferred = state.get("segment_deferred")
        if deferred is None:
            return {}
        status: SegmentStatus = "handoff" if update.get("escalation_reason") else "resolved"
        return {"intent_segments": [{**deferred, "status": status}], "segment_deferred": None}
    # handoff_summary (D19)
    existing = state.get("intent_segments") or []
    head = _queue_head(state)
    if (
        head is not None
        and state.get("degraded")
        and state.get("escalation_reason") == "llm_unavailable"
        and head in get_policies().escalation.degraded_handoff_intents
        and all(seg["intent"] != head for seg in existing)
    ):
        # PQ1: no flow node ran, and only the head intent is handed off.
        return {"intent_segments": [{"intent": head, "route": name, "status": "handoff"}]}
    if existing:
        return {}
    return {
        "intent_segments": [
            {"intent": i, "route": name, "status": "handoff"} for i in _real_intents(state)
        ]
    }


def _track_segments[N: Callable[..., Awaitable[dict[str, Any]]]](name: str, node: N) -> N:
    """Wrap a node so the turn's per-intent segments are recorded (analytics D14).

    Reads the node's update and the state, never calls anything: it adds
    `intent_segments` (and, for a flow, the deferral and offer bookkeeping) and
    removes `segment_mark`, which is a flow's message to this wrapper and not a
    channel. An LLM node gets no write path from here (R6).
    """

    @functools.wraps(node)
    async def tracked(state: GraphState, config: RunnableConfig) -> dict[str, Any]:
        update = dict(await node(state, config) or {})
        extra = _segment_update(name, state, update)
        update.pop("segment_mark", None)
        return {**update, **extra}

    return cast(N, tracked)


def build_graph(
    checkpointer: BaseCheckpointSaver[Any],
    system: Literal["proposed", "baseline"] = "proposed",
) -> CompiledStateGraph[GraphState, Any, TurnInput, TurnOutput]:
    """Compile the v0 turn graph (D8, D9, D20).

    `system="baseline"` (D17) swaps exactly four nodes -- `understand`,
    `compose`, `handoff_summary` and `abstain`'s wording -- for LLM-free
    ones. Tools, policy, flows and graph shape stay identical.
    """
    from app.domains.conversation.agent.confirm import agent_plan
    from app.domains.conversation.agent.node import agent
    from app.domains.conversation.agent.step_up import agent_address, agent_step_up
    from app.domains.conversation.baseline.template_compose import (
        baseline_abstain,
        baseline_compose,
        baseline_handoff_summary,
        baseline_understand,
    )
    from app.domains.conversation.flows.card_block import card_block
    from app.domains.conversation.flows.card_info import card_info
    from app.domains.conversation.flows.card_unlock import card_unlock
    from app.domains.conversation.flows.decline_explain import decline_explain
    from app.domains.conversation.flows.replacement import replacement
    from app.domains.conversation.flows.tx_explain import tx_explain
    from app.domains.conversation.flows.tx_search import tx_search
    from app.domains.conversation.flows.unrecognized_charge import unrecognized_charge
    from app.domains.conversation.nodes import (
        abstain,
        compose,
        enqueue,
        fallback,
        finish,
        handoff,
        handoff_summary,
        load_session,
        next_intent,
        relay_to_agent,
        route,
        smalltalk,
        summarize,
        understand,
        unsupported,
    )
    from app.domains.conversation.nodes.step_up_exit import otp_cancel, step_up_failed

    graph = StateGraph(GraphState, input_schema=TurnInput, output_schema=TurnOutput)
    graph.add_node("load_session", load_session)
    # OTP exits (S2 D28, D30): code-only, on both systems.
    graph.add_node("step_up_failed", _guard_access(step_up_failed))
    graph.add_node("otp_cancel", _guard_access(otp_cancel))
    graph.add_edge("step_up_failed", "handoff_summary")
    graph.add_edge("otp_cancel", "finish")
    baseline = system == "baseline"
    graph.add_node("understand", baseline_understand if baseline else understand)
    # The baseline never summarizes (D17): it has no LLM and no memory.
    if not baseline:
        graph.add_node("summarize", summarize)
        graph.add_node("agent", _guard_access(agent))
        graph.add_node("agent_plan", _guard_access(agent_plan))
        graph.add_conditional_edges(
            "agent_plan",
            _after_agent_plan,
            {
                "agent": "agent",
                "finish": "finish",
                "fallback": "fallback",
                "handoff_summary": "handoff_summary",
            },
        )
        for pause_node, pause_fn in (
            ("agent_step_up", agent_step_up),
            ("agent_address", agent_address),
        ):
            graph.add_node(pause_node, _guard_access(pause_fn))
            graph.add_conditional_edges(
                pause_node,
                _after_agent_pause,
                {
                    "agent": "agent",
                    "finish": "finish",
                    "fallback": "fallback",
                    "handoff_summary": "handoff_summary",
                },
            )
        graph.add_conditional_edges(
            "summarize", _after_summarize, {"agent": "agent", "understand": "understand"}
        )
        graph.add_conditional_edges(
            "agent",
            _after_agent,
            {
                "finish": "finish",
                "understand": "understand",
                "fallback": "fallback",
                "handoff_summary": "handoff_summary",
            },
        )
    graph.add_node("smalltalk", smalltalk)
    graph.add_node("enqueue", enqueue)
    graph.add_node(
        "card_info",
        _track_segments("card_info", _keep_open_question("card_info", _guard_access(card_info))),
    )
    graph.add_node(
        "card_block",
        _track_segments("card_block", _keep_open_question("card_block", _guard_access(card_block))),
    )
    graph.add_node(
        "card_unlock",
        _track_segments(
            "card_unlock", _keep_open_question("card_unlock", _guard_access(card_unlock))
        ),
    )
    graph.add_node(
        "replacement",
        _track_segments(
            "replacement", _keep_open_question("replacement", _guard_access(replacement))
        ),
    )
    graph.add_node(
        "unrecognized_charge",
        _track_segments(
            "unrecognized_charge",
            _keep_open_question("unrecognized_charge", _guard_access(unrecognized_charge)),
        ),
    )
    graph.add_node(
        "decline_explain",
        _track_segments(
            "decline_explain",
            _keep_open_question("decline_explain", _guard_access(decline_explain)),
        ),
    )
    graph.add_node(
        "tx_search",
        _track_segments("tx_search", _keep_open_question("tx_search", _guard_access(tx_search))),
    )
    graph.add_node(
        "tx_explain",
        _track_segments("tx_explain", _keep_open_question("tx_explain", _guard_access(tx_explain))),
    )
    graph.add_node("unsupported", _track_segments("unsupported", unsupported))
    graph.add_node("fallback", fallback)
    graph.add_node("compose", _track_segments("compose", baseline_compose if baseline else compose))
    graph.add_node("next_intent", next_intent)
    graph.add_node("finish", finish)
    graph.add_node("abstain", _track_segments("abstain", baseline_abstain if baseline else abstain))
    graph.add_node(
        "handoff_summary",
        _track_segments(
            "handoff_summary", baseline_handoff_summary if baseline else handoff_summary
        ),
    )
    graph.add_node("handoff", handoff)
    graph.add_node("relay_to_agent", relay_to_agent)

    graph.set_entry_point("load_session")
    graph.add_conditional_edges(
        "load_session",
        _entry,
        {
            "understand": "understand" if baseline else "summarize",
            # The agent exists on the proposed system only (D17 baseline has no LLM).
            "summarize": "understand" if baseline else "summarize",
            "agent": "understand" if baseline else "agent",
            "agent_plan": "smalltalk" if baseline else "agent_plan",
            "agent_step_up": "smalltalk" if baseline else "agent_step_up",
            "agent_address": "smalltalk" if baseline else "agent_address",
            "step_up_failed": "step_up_failed",
            "otp_cancel": "otp_cancel",
            "relay_to_agent": "relay_to_agent",
            "fallback": "fallback",
            "smalltalk": "smalltalk",
            "card_info": "card_info",
            "card_block": "card_block",
            "card_unlock": "card_unlock",
            "replacement": "replacement",
            "unrecognized_charge": "unrecognized_charge",
            "decline_explain": "decline_explain",
            "tx_search": "tx_search",
            "tx_explain": "tx_explain",
        },
    )
    graph.add_conditional_edges(
        "understand",
        route,
        {
            "fallback": "fallback",
            "unsupported": "unsupported",
            "abstain": "abstain",
            "handoff_summary": "handoff_summary",
            "smalltalk": "smalltalk",
            "enqueue": "enqueue",
            "card_info": "card_info",
            "card_block": "card_block",
            "card_unlock": "card_unlock",
            "replacement": "replacement",
            "unrecognized_charge": "unrecognized_charge",
            "decline_explain": "decline_explain",
            "tx_search": "tx_search",
            "tx_explain": "tx_explain",
        },
    )
    graph.add_conditional_edges(
        "enqueue",
        _dispatch,
        {
            "card_info": "card_info",
            "card_block": "card_block",
            "card_unlock": "card_unlock",
            "replacement": "replacement",
            "unrecognized_charge": "unrecognized_charge",
            "decline_explain": "decline_explain",
            "tx_search": "tx_search",
            "tx_explain": "tx_explain",
            "unsupported": "unsupported",
            "fallback": "fallback",
            "finish": "finish",
        },
    )
    graph.add_conditional_edges(
        "card_info",
        _after_flow,
        {
            "compose": "compose",
            "fallback": "fallback",
            "handoff_summary": "handoff_summary",
            "finish": "finish",
            "next_intent": "next_intent",
        },
    )
    graph.add_conditional_edges(
        "card_block",
        _after_flow,
        {
            "compose": "compose",
            "fallback": "fallback",
            "handoff_summary": "handoff_summary",
            "finish": "finish",
            "next_intent": "next_intent",
        },
    )
    graph.add_conditional_edges(
        "card_unlock",
        _after_flow,
        {
            "compose": "compose",
            "fallback": "fallback",
            "handoff_summary": "handoff_summary",
            "finish": "finish",
            "next_intent": "next_intent",
        },
    )
    graph.add_conditional_edges(
        "replacement",
        _after_flow,
        {
            "compose": "compose",
            "fallback": "fallback",
            "handoff_summary": "handoff_summary",
            "finish": "finish",
            "next_intent": "next_intent",
        },
    )
    graph.add_conditional_edges(
        "unrecognized_charge",
        _after_flow,
        {
            "compose": "compose",
            "fallback": "fallback",
            "handoff_summary": "handoff_summary",
            "finish": "finish",
            "next_intent": "next_intent",
        },
    )
    graph.add_conditional_edges(
        "decline_explain",
        _after_flow,
        {
            "compose": "compose",
            "fallback": "fallback",
            "handoff_summary": "handoff_summary",
            "finish": "finish",
            "next_intent": "next_intent",
        },
    )
    graph.add_conditional_edges(
        "tx_search",
        _after_flow,
        {
            "compose": "compose",
            "fallback": "fallback",
            "handoff_summary": "handoff_summary",
            "finish": "finish",
            "next_intent": "next_intent",
        },
    )
    graph.add_conditional_edges(
        "tx_explain",
        _after_flow,
        {
            "compose": "compose",
            "fallback": "fallback",
            "handoff_summary": "handoff_summary",
            "finish": "finish",
            "next_intent": "next_intent",
        },
    )
    graph.add_conditional_edges(
        "compose",
        _after_compose,
        {"fallback": "fallback", "finish": "finish", "next_intent": "next_intent"},
    )
    graph.add_conditional_edges(
        "unsupported",
        _after_unsupported,
        {"handoff_summary": "handoff_summary", "finish": "finish", "next_intent": "next_intent"},
    )
    graph.add_conditional_edges(
        "abstain", _after_segment, {"finish": "finish", "next_intent": "next_intent"}
    )
    graph.add_edge("handoff_summary", "handoff")
    graph.add_edge("handoff", "finish")
    graph.add_edge("relay_to_agent", "finish")
    graph.add_conditional_edges(
        "fallback",
        _after_fallback,
        {"handoff_summary": "handoff_summary", "finish": "finish", "next_intent": "next_intent"},
    )
    graph.add_edge("smalltalk", "finish")
    graph.add_conditional_edges(
        "next_intent",
        _dispatch,
        {
            "card_info": "card_info",
            "card_block": "card_block",
            "card_unlock": "card_unlock",
            "replacement": "replacement",
            "unrecognized_charge": "unrecognized_charge",
            "decline_explain": "decline_explain",
            "tx_search": "tx_search",
            "tx_explain": "tx_explain",
            "unsupported": "unsupported",
            "fallback": "fallback",
            "finish": "finish",
        },
    )
    graph.add_edge("finish", END)

    return graph.compile(checkpointer=checkpointer)


async def run_turn(
    graph: CompiledStateGraph[GraphState, Any, TurnInput, TurnOutput],
    text: str,
    *,
    config: RunnableConfig,
    confirmation: ConfirmationDecision | None = None,
    resume: Literal["step_up", "step_up_cancel", "step_up_failed"] | None = None,
    selection: TxSelection | None = None,
    card_selection: CardSelection | None = None,
) -> tuple[str, DebugInfo]:
    """Run one turn and build its debug line (D9, D20, `07` §1).

    `route` (in the debug line's sense) is read off the actual node
    sequence -- the first of `_BRANCH_NODES` seen once `understand`/`_entry`
    resolves -- not by re-calling a routing function a second time: a second
    call would see the same state and agree, but reading the run itself is
    the one source of truth a bug in that agreement couldn't fake. `pending`
    is read from the checkpointed state after the run, since a paused turn's
    last node may not be the one that set it (e.g. `card_info`'s `Ask`
    outcome, then `compose`, then `finish`).
    """
    route_taken: str | None = None
    nlu: NLUResult | None = None
    language: Literal["es", "pt"] = "es"
    reply = ""
    ui_kinds: list[str] = []

    async for update in graph.astream(
        {
            "user_text": text,
            "confirmation": confirmation,
            "resume": resume,
            "selection": selection,
            "card_selection": card_selection,
        },
        config=config,
        stream_mode="updates",
    ):
        for node_name, values in update.items():
            # A passed or degraded agent turn is not the agent's: the pipeline that
            # takes it names the route. Only a replying agent turn does.
            if node_name == "agent" and not (values or {}).get("agent_labels"):
                continue
            # A node whose returned update is empty (e.g. `next_intent` with
            # nothing left to pop) streams as `None`, not `{}` (D20).
            # `relay_to_agent` returns `{}` too, and it is still the route.
            if values is None:
                if route_taken is None and node_name in _BRANCH_NODES:
                    route_taken = node_name
                continue
            if node_name == "understand":
                nlu = values.get("nlu")
                language = values.get("language", language)
            elif route_taken is None and node_name in _BRANCH_NODES:
                route_taken = node_name
            reply_value = values.get("reply")
            if reply_value is not None:
                reply = reply_value
            if "ui" in values and values["ui"] is not None:
                ui_kinds = [event.kind for event in values["ui"]]

    bank_tools = config["configurable"]["bank_tools"]
    tools_called = list(getattr(bank_tools, "calls", []))

    final_state = await graph.aget_state(config)
    pending = final_state.values.get("pending")
    pending_str = f"{pending['flow']}.{pending['awaiting_slot']}" if pending else None

    debug = DebugInfo(
        language=language,
        status=nlu.status if nlu is not None else None,
        intents=nlu.intents if nlu is not None else [],
        slots=nlu.slots if nlu is not None else NLUSlots(),
        route=route_taken or "fallback",
        tools_called=tools_called,
        pending=pending_str,
        ui=ui_kinds,
        degraded=bool(final_state.values.get("degraded", False)),
    )
    return reply, debug


def _print_mermaid() -> None:
    """`python -m app.domains.conversation.graph --mermaid` (D19, B3).

    A fresh `MemorySaver` is enough here: the diagram is a property of the
    graph's shape, not of any run's checkpointed state.
    """
    graph = build_graph(MemorySaver())
    print(graph.get_graph().draw_mermaid())


if __name__ == "__main__":
    if "--mermaid" in sys.argv:
        _print_mermaid()
