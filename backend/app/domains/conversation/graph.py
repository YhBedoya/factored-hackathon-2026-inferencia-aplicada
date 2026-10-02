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
  this turn should try to resume whatever was waiting on it.
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

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.errors import AccessDenied
from app.domains.audit.schemas import NullAuditRecorder
from app.domains.conversation.schemas import Intent, NLUResult, NLUSlots, NLUStatus
from app.domains.conversation.state import TurnState, _reduce_segments
from app.domains.conversation.templates import get_template
from app.domains.conversation.ui import UIEvent
from app.domains.handoff.schemas import HandoffReason
from app.domains.policy.registry import get_policies

__all__ = [
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
    whatever paused on it. `selection` (D4-B D7) is the same shape again for
    `unrecognized_charge`'s pick step: every caller passes it explicitly
    (`None` otherwise), and when it is set (and the checkpoint is actually
    paused on it) `_entry` skips `understand` too -- the pick is never run
    through NLU, and never saved as a customer message.
    """

    user_text: str
    confirmation: NotRequired[ConfirmationDecision | None]
    resume: NotRequired[Literal["step_up"] | None]
    selection: NotRequired[TxSelection | None]
    introduced: NotRequired[bool]


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
    """

    user_text: NotRequired[str]
    reply: NotRequired[str]
    confirmation: NotRequired[ConfirmationDecision | None]
    resume: NotRequired[Literal["step_up"] | None]
    selection: NotRequired[TxSelection | None]
    ui: NotRequired[list[UIEvent]]
    segments: NotRequired[Annotated[list[str], _reduce_segments]]
    handoff_request: NotRequired[str]
    grounding: NotRequired[str]
    actions_at_turn_start: NotRequired[int]
    write_failed: NotRequired[bool]
    # personalidad-cardy D6: "sí" to the closing suggestion this turn. Reset by
    # `load_session`, set by `enqueue`, read only by `tx_search` as a criterion.
    suggestion_accepted: NotRequired[bool]


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
)

_MANAGEMENT_INTENTS: frozenset[Intent] = frozenset({"greeting", "thanks_close", "affirm", "deny"})
"""Conversation-management intents (`02` §1): they never start or continue a
flow on their own, so `route` sends a turn made only of these to `smalltalk`,
and `enqueue` (P1, D20) strips them out of the intent queue.
"""

_INTENT_NODES: dict[Intent, str] = {
    "card_status": "card_info",
    "balance_due": "card_info",
    "card_block": "card_block",
    "card_unlock": "card_unlock",
    "replacement_request": "replacement",
    "unrecognized_charge": "unrecognized_charge",
    "decline_explain": "decline_explain",
    "transaction_search": "tx_search",
    "pending_reversal_explain": "tx_explain",
}
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
    """
    if state.get("mode") == "human":
        return "relay_to_agent"
    # D10: the kill switch (or a failure `load_session` already saw) beats
    # steps 0-3, so typed, button, step-up and pick turns all fall back.
    if state.get("escalation_reason") == "llm_unavailable":
        return "fallback"
    pending = state.get("pending")
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
    return "understand"


def _dispatch(state: GraphState) -> str:
    """Conditional edge shared by `enqueue` and `next_intent` (D8, D20): the
    queue's head decides the flow node through `_INTENT_NODES`; an empty
    queue (nothing left to answer) ends the turn at `finish`.
    """
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
            return {"unauthorized_attempts": attempt, "segments": [text]}

    return cast(N, guarded)


def build_graph(
    checkpointer: BaseCheckpointSaver[Any],
    system: Literal["proposed", "baseline"] = "proposed",
) -> CompiledStateGraph[GraphState, Any, TurnInput, TurnOutput]:
    """Compile the v0 turn graph (D8, D9, D20).

    `system="baseline"` (D17) swaps exactly four nodes -- `understand`,
    `compose`, `handoff_summary` and `abstain`'s wording -- for LLM-free
    ones. Tools, policy, flows and graph shape stay identical.
    """
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

    graph = StateGraph(GraphState, input_schema=TurnInput, output_schema=TurnOutput)
    graph.add_node("load_session", load_session)
    baseline = system == "baseline"
    graph.add_node("understand", baseline_understand if baseline else understand)
    # The baseline never summarizes (D17): it has no LLM and no memory.
    if not baseline:
        graph.add_node("summarize", summarize)
        graph.add_edge("summarize", "understand")
    graph.add_node("smalltalk", smalltalk)
    graph.add_node("enqueue", enqueue)
    graph.add_node("card_info", _guard_access(card_info))
    graph.add_node("card_block", _guard_access(card_block))
    graph.add_node("card_unlock", _guard_access(card_unlock))
    graph.add_node("replacement", _guard_access(replacement))
    graph.add_node("unrecognized_charge", _guard_access(unrecognized_charge))
    graph.add_node("decline_explain", _guard_access(decline_explain))
    graph.add_node("tx_search", _guard_access(tx_search))
    graph.add_node("tx_explain", _guard_access(tx_explain))
    graph.add_node("unsupported", unsupported)
    graph.add_node("fallback", fallback)
    graph.add_node("compose", baseline_compose if baseline else compose)
    graph.add_node("next_intent", next_intent)
    graph.add_node("finish", finish)
    graph.add_node("abstain", baseline_abstain if baseline else abstain)
    graph.add_node("handoff_summary", baseline_handoff_summary if baseline else handoff_summary)
    graph.add_node("handoff", handoff)
    graph.add_node("relay_to_agent", relay_to_agent)

    graph.set_entry_point("load_session")
    graph.add_conditional_edges(
        "load_session",
        _entry,
        {
            "understand": "understand" if baseline else "summarize",
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
    resume: Literal["step_up"] | None = None,
    selection: TxSelection | None = None,
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
        {"user_text": text, "confirmation": confirmation, "resume": resume, "selection": selection},
        config=config,
        stream_mode="updates",
    ):
        for node_name, values in update.items():
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
