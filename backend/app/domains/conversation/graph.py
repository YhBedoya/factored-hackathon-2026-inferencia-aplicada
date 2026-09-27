"""The v0 turn graph: I/O channels, `build_graph`, `run_turn`, `DebugInfo` (D8, Q2).

`TurnInput`/`TurnOutput` are this graph's own channels, not part of the K3
`TurnState` contract (`docs/plans/d1-b-agent-sandbox.md` Q2): `user_text` is
what the sandbox writes in before a turn runs, `reply` is what it reads out
once `compose`/`unsupported`/`fallback` runs. `GraphState` is `TurnState` plus
both, with `user_text`/`reply` re-declared `NotRequired` here (they are
required in their own `TypedDict`s) so a node's partial-update return dict
never has to restate keys it did not touch.

`build_graph` wires `load_session -> understand -> route` (conditional to
`card_info`/`unsupported`/`fallback`), then `card_info -> compose` or
`-> fallback` when it set `escalation_reason`, with `compose`/`unsupported`/
`fallback` all terminal (D8). The node modules import `GraphState`/
`TurnInput`/`TurnOutput` from here, so `build_graph` imports them itself,
inside its own body, rather than at module level -- importing them at the top
would be a cycle.

`run_turn` drives one turn end to end and assembles the sandbox's debug line
(`07` §1): the reply from the `reply` output channel, the route from the node
names actually seen in the `astream` update sequence (not by calling
`nodes.route.route` a second time), and `tools_called` from whatever the
caller's `bank_tools` records on itself (read with `getattr`, so a plain
`FakeBank` with no such attribute just reports none called).
"""

import sys
from typing import Any, Literal, NotRequired, TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel, ConfigDict

from app.domains.conversation.schemas import Intent, NLUResult, NLUSlots, NLUStatus
from app.domains.conversation.state import TurnState
from app.domains.conversation.ui import UIEvent

__all__ = [
    "ConfirmationDecision",
    "DebugInfo",
    "GraphState",
    "TurnInput",
    "TurnOutput",
    "build_graph",
    "run_turn",
]


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
    LLM call; the routing that does the skipping is B5).
    """

    user_text: str
    confirmation: NotRequired[ConfirmationDecision | None]


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
    """

    user_text: NotRequired[str]
    reply: NotRequired[str]
    confirmation: NotRequired[ConfirmationDecision | None]
    ui: NotRequired[list[UIEvent]]


class DebugInfo(BaseModel):
    """The sandbox's per-turn debug line fields (`07` §1, §"Contracts")."""

    model_config = ConfigDict(frozen=True)

    language: Literal["es", "pt"]
    status: NLUStatus | None
    intents: list[Intent]
    slots: NLUSlots
    route: str
    tools_called: list[str]


_BRANCH_NODES = ("card_info", "unsupported", "fallback")


def _after_card_info(state: GraphState) -> Literal["compose", "fallback"]:
    """Conditional edge after `card_info` (D8): a set `escalation_reason`
    (tool_unavailable/no_cards/clarification_exhausted) means there is no
    card to talk about, so go straight to the fixed-template `fallback`
    node; otherwise `compose` writes the reply from this turn's facts.
    """
    return "fallback" if state.get("escalation_reason") else "compose"


def build_graph(
    checkpointer: BaseCheckpointSaver[Any],
) -> CompiledStateGraph[GraphState, Any, TurnInput, TurnOutput]:
    """Compile the v0 turn graph (D8, D9)."""
    from app.domains.conversation.flows.card_info import card_info
    from app.domains.conversation.nodes import (
        compose,
        fallback,
        load_session,
        route,
        understand,
        unsupported,
    )

    graph = StateGraph(GraphState, input_schema=TurnInput, output_schema=TurnOutput)
    graph.add_node("load_session", load_session)
    graph.add_node("understand", understand)
    graph.add_node("card_info", card_info)
    graph.add_node("unsupported", unsupported)
    graph.add_node("fallback", fallback)
    graph.add_node("compose", compose)

    graph.set_entry_point("load_session")
    graph.add_edge("load_session", "understand")
    graph.add_conditional_edges(
        "understand",
        route,
        {"card_info": "card_info", "unsupported": "unsupported", "fallback": "fallback"},
    )
    graph.add_conditional_edges(
        "card_info", _after_card_info, {"compose": "compose", "fallback": "fallback"}
    )
    graph.add_edge("compose", END)
    graph.add_edge("unsupported", END)
    graph.add_edge("fallback", END)

    return graph.compile(checkpointer=checkpointer)


async def run_turn(
    graph: CompiledStateGraph[GraphState, Any, TurnInput, TurnOutput],
    text: str,
    *,
    config: RunnableConfig,
) -> tuple[str, DebugInfo]:
    """Run one turn and build its debug line (D9, `07` §1).

    `route` is read off the actual node sequence (the first of
    `card_info`/`unsupported`/`fallback` seen right after `understand`
    completes), not by re-calling `nodes.route.route`: a second call would
    see the same state and agree, but reading the run itself is the one
    source of truth a bug in that agreement couldn't fake.
    """
    route_taken: str | None = None
    nlu: NLUResult | None = None
    language: Literal["es", "pt"] = "es"
    reply = ""

    async for update in graph.astream(
        {"user_text": text, "confirmation": None}, config=config, stream_mode="updates"
    ):
        for node_name, values in update.items():
            if node_name == "understand":
                nlu = values.get("nlu")
                language = values.get("language", language)
            elif route_taken is None and node_name in _BRANCH_NODES:
                route_taken = node_name
            reply_value = values.get("reply")
            if reply_value is not None:
                reply = reply_value

    bank_tools = config["configurable"]["bank_tools"]
    tools_called = list(getattr(bank_tools, "calls", []))

    debug = DebugInfo(
        language=language,
        status=nlu.status if nlu is not None else None,
        intents=nlu.intents if nlu is not None else [],
        slots=nlu.slots if nlu is not None else NLUSlots(),
        route=route_taken or "fallback",
        tools_called=tools_called,
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
