"""Runs one turn against a hosted graph and publishes its events (D14).

`start_turn` is the API's one entry point: it takes the turn lock first (a
`SET turn:<conversation_id> <turn_id> NX EX 120`, so two concurrent posts to
the same conversation can't both run), persists the customer's message (only
when this is a typed turn, D6), then schedules the turn itself as an
`asyncio.Task` on `host.tasks` and returns right away with the `turn_id` --
`POST /messages`/`POST /confirmations/{token_id}` both answer `202` without
waiting for the graph to finish. Exactly one of `text`, `resume`,
`confirmation` or `selection` is set on any one call (D6, D7): a typed turn,
a step-up resume, a button confirm/cancel, or a transaction pick.
`checkpointed_confirmation_token` is the route's second D7 gate for a
confirmation -- the same `graph.aget_state(...).values.get(
"confirmation_token_id")` read the sandbox's `/confirm` already does --
and `checkpointed_offer` is the analogous read for a pick (`pending` + the
offering flow's own sub-state, `dispute` or `decline`, T7).

The turn task builds its `ToolContext`, its one turn-bound `AuditRecorder`
and its read/write tools only through `registry` (R1, D13, D17): nothing
here ever reads `customer_id` off anything but the route's `Session`. The
same recorder that `RecordingBankTools` and `ConfirmedWriteTools` audit
their tool calls through also gets this module's own turn-level events:
`nlu_result` (from `understand`'s update), `rule_hit` for any
`escalation_reason` a flow sets this turn, and `reply_sent` just before the
bot's reply is published (D14). A recording failure at this level is logged
`audit.write_failed` and never fails the turn (D15) -- only a failed
`tool_call` audit inside a read or write blocks that call itself. It
mirrors `graph.run_turn`'s astream loop and debug assembly (not import it:
`run_turn` drives one call and returns, this drives one call and publishes
each step as it happens), then
publishes the bot's `ui`/`message`/`debug`/`done` events in order and
persists the bot reply. On any exception it logs `turn.failed` -- fields
only, no user text and no PII -- and publishes `error`/`done` instead.

The lock is released in `finally` only if it still holds this turn's own
`turn_id`: a Lua script reads and compares before it deletes, so a lock this
turn's own TTL already dropped (and a later turn already re-acquired) is
never deleted out from under that later turn.
"""

import asyncio
import functools
from collections.abc import Sequence
from typing import Any, Literal
from uuid import UUID, uuid4

import structlog
from langchain_core.runnables import RunnableConfig
from opentelemetry import trace
from pydantic import JsonValue

from app.core import events
from app.core.config import get_settings
from app.core.logging import bind_conversation_id, bind_turn_id
from app.core.redis import get_redis
from app.domains.audit.schemas import AuditType
from app.domains.conversation import fact_values, store
from app.domains.conversation.graph import (
    CardSelection,
    ConfirmationDecision,
    DebugInfo,
    TurnInput,
    TxSelection,
)
from app.domains.conversation.hosting import TurnHost
from app.domains.conversation.schemas import NLUResult, NLUSlots
from app.domains.conversation.state import (
    DeclineState,
    DisputeState,
    HistoryMessage,
    Pending,
    TxOfferState,
)
from app.domains.conversation.tools import registry
from app.domains.conversation.tools.handoff import ServiceHandoffTools
from app.domains.conversation.ui import UIEvent
from app.domains.identity.models import Session
from app.domains.safety.vault import PiiVault, PostgresPiiVault

__all__ = [
    "TurnInProgress",
    "checkpointed_confirmation_token",
    "checkpointed_offer",
    "start_turn",
]

_logger = structlog.get_logger()

_LOCK_TTL_SECONDS = 120
# Mirrors `graph._BRANCH_NODES`, not imported (same "mirror, not import"
# convention `registry.RecordingBankTools` set for the sandbox's recorder):
# this module's job is to drive a hosted graph, not to reach into another
# module's private constant. `agent` is not in it on purpose: an agent turn's
# route is `agent_labels["route"]`, read from the node's update below.
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
    "handoff",
)


async def _introduced_seed(
    graph: Any, config: RunnableConfig, conversation_id: UUID
) -> dict[str, Any]:
    """D10: on a conversation's first graph turn, when the welcome (a stored bot
    message) already introduced Cardy, seed `introduced=True` and put the
    welcome's masked text at the head of `history`, so the model sees how the
    conversation opened (amends naturalidad-cardy D8). `{}` otherwise.
    """
    checkpoint = await graph.aget_state(config)
    if "introduced" in checkpoint.values:
        return {}
    rows = await store.list_messages(conversation_id)
    welcome: list[HistoryMessage] = []
    for row in rows:
        if row.role != "bot":
            break
        if row.content_masked:
            welcome.append({"role": "cardy", "text": row.content_masked})
    if not any(row.role == "bot" for row in rows):
        return {}
    seed: dict[str, Any] = {"introduced": True}
    if welcome:
        seed["history"] = [*welcome, *(checkpoint.values.get("history") or [])]
    return seed


_RELEASE_LOCK_SCRIPT = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
end
return 0
"""


class TurnInProgress(Exception):
    """`start_turn` raises this when the conversation's turn lock is already
    held. Nothing is persisted before this is raised (D14).
    """


async def start_turn(
    host: TurnHost,
    *,
    session: Session,
    conversation_id: UUID,
    trace_id: str,
    text: str | None = None,
    resume: Literal["step_up"] | None = None,
    confirmation: ConfirmationDecision | None = None,
    selection: TxSelection | None = None,
    card_selection: CardSelection | None = None,
) -> UUID:
    """Take the turn lock, persist the customer message (only when `text` is
    set, D6), and schedule the turn task. Exactly one of `text`, `resume`,
    `confirmation`, `selection` or `card_selection` must be set -- `ValueError`
    otherwise. `selection` (D4-B D7) and `card_selection` (replacement picker)
    are never persisted as a message, same as `resume` and `confirmation`:
    the route's own D7 gate is the injection guard, not this function.
    Raises `TurnInProgress` (nothing persisted) if the lock is already held.
    """
    if (
        sum(value is not None for value in (text, resume, confirmation, selection, card_selection))
        != 1
    ):
        raise ValueError(
            "start_turn takes exactly one of text, resume, confirmation, selection, "
            "or card_selection"
        )

    turn_id = uuid4()
    lock_key = f"turn:{conversation_id}"
    acquired = await get_redis().set(lock_key, str(turn_id), nx=True, ex=_LOCK_TTL_SECONDS)
    if not acquired:
        raise TurnInProgress(f"a turn is already running for conversation {conversation_id}")

    vault = PostgresPiiVault(conversation_id)
    graph_text = text
    if text is not None:
        try:
            # D4: mask once, here, so the checkpoint never holds the raw text.
            # `mask()` flushes the tokens; `text` stays raw only for the
            # `relay_to_agent` echo (D7) and the encrypted `content`.
            ctx = registry.build_tool_context(session, conversation_id, trace_id)
            graph_text = await vault.mask(text, await registry.known_pii(ctx))
            await store.add_message(
                conversation_id,
                turn_id,
                role="customer",
                content=text,
                content_masked=graph_text,
            )
        except BaseException:
            # Nothing was scheduled, so nobody else will free the lock.
            await get_redis().eval(_RELEASE_LOCK_SCRIPT, 1, lock_key, str(turn_id))
            raise

    task = asyncio.create_task(
        _run_turn_traced(
            host,
            session=session,
            conversation_id=conversation_id,
            turn_id=turn_id,
            text=text,
            graph_text=graph_text,
            vault=vault,
            resume=resume,
            confirmation=confirmation,
            selection=selection,
            card_selection=card_selection,
            trace_id=trace_id,
        )
    )
    host.tasks.add(task)
    task.add_done_callback(host.tasks.discard)
    return turn_id


async def _run_turn_traced(host: TurnHost, **kwargs: Any) -> None:
    """Run the turn inside its own span. The request's span ends (202) before
    the background task finishes, so a per-turn attribute like `cardy.degraded`
    needs a span that lives as long as the turn. The task copied the request's
    context, so this span is a child in the same trace."""
    with trace.get_tracer(__name__).start_as_current_span("cardy.turn"):
        await _run_turn(host, **kwargs)


async def checkpointed_confirmation_token(host: TurnHost, conversation_id: UUID) -> str | None:
    """The `confirmation_token_id` this conversation's plan last checkpointed
    (D7's second gate, on top of `RedisConfirmationStore.is_open`): the same
    `graph.aget_state(...).values.get("confirmation_token_id")` read the
    sandbox's `/confirm` command already does. `None` on a conversation with
    no checkpoint yet or nothing pending.
    """
    state = await host.graph.aget_state({"configurable": {"thread_id": str(conversation_id)}})
    return state.values.get("confirmation_token_id")


async def checkpointed_offer(
    host: TurnHost, conversation_id: UUID
) -> tuple[Pending | None, set[str], bool]:
    """This conversation's last-checkpointed `pending`, the ids its own pick
    actually offered, and whether that pick was multi-select (T7, D7's route
    gate, generalizing D4-B's `checkpointed_dispute` to also cover
    `decline_explain`'s single-pick offer, D3): the same read
    `checkpointed_confirmation_token` does, for the pick's own three facts --
    "is a transaction list actually open", "what ids did it offer" and "how
    many can be picked". Reads `decline` (multi `False`) when
    `pending["flow"] == "decline_explain"`, `tx_offer` (multi `False`, this
    card's B1) when the flow is `tx_search`, `tx_explain` or `agent`, else `dispute`
    (multi `True`, D4-B's shape) -- none of these flows ever share a
    checkpoint slot (`state.py`'s `DeclineState`/`DisputeState`/
    `TxOfferState`). `(None, set(), True)` on a conversation with no
    checkpoint yet, or with nothing pending.
    """
    state = await host.graph.aget_state({"configurable": {"thread_id": str(conversation_id)}})
    pending: Pending | None = state.values.get("pending")
    if pending is not None and pending["flow"] == "decline_explain":
        decline: DeclineState | None = state.values.get("decline")
        offered = set(decline["offered_tx_ids"]) if decline is not None else set()
        return pending, offered, False
    if pending is not None and pending["flow"] in {"tx_search", "tx_explain", "agent"}:
        tx_offer: TxOfferState | None = state.values.get("tx_offer")
        offered = set(tx_offer["offered_tx_ids"]) if tx_offer is not None else set()
        return pending, offered, False
    dispute: DisputeState | None = state.values.get("dispute")
    offered = set(dispute["offered_tx_ids"]) if dispute is not None else set()
    return pending, offered, True


async def checkpointed_replacement_offer(
    host: TurnHost, conversation_id: UUID
) -> tuple[Pending | None, set[str]]:
    """This conversation's last-checkpointed `pending` and the card ids its
    replacement picker offered (`replacement_card_ids`; empty when the offer
    was a single card or nothing is offered). The route's gate for a
    `card_selection` body and for typed text at the `replacement_cards`
    pause, same read as `checkpointed_offer`.
    """
    state = await host.graph.aget_state({"configurable": {"thread_id": str(conversation_id)}})
    pending: Pending | None = state.values.get("pending")
    return pending, set(state.values.get("replacement_card_ids") or [])


_GROUNDING_RANK = {"ok": 0, "regenerated": 1, "template": 2}


def _worse_grounding(current: str | None, new: str) -> str:
    if current is None or _GROUNDING_RANK.get(new, 0) > _GROUNDING_RANK.get(current, 0):
        return new
    return current


def _nlu_source(degraded: bool, host: TurnHost) -> dict[str, JsonValue]:
    """`nlu_result` provenance (ADR-032): the classifier answered when the
    understand update was degraded. Versions are code-set identifiers."""
    if degraded and host.classifier is not None:
        return {
            "source": "classifier",
            "classifier_version": host.classifier.version,
            "label_set_version": host.classifier.label_set_version,
        }
    return {"source": "llm"}


async def _run_turn(
    host: TurnHost,
    *,
    session: Session,
    conversation_id: UUID,
    turn_id: UUID,
    text: str | None,
    graph_text: str | None,
    vault: PiiVault,
    resume: Literal["step_up"] | None,
    confirmation: ConfirmationDecision | None,
    selection: TxSelection | None,
    trace_id: str,
    card_selection: CardSelection | None = None,
) -> None:
    lock_key = f"turn:{conversation_id}"
    # `text` is the raw typed text (relay echo only); the graph gets `graph_text`.
    # `create_task` runs on a copy of the request's context, so these bindings
    # die with the task and can't leak into a later turn. The `llm.call` lines
    # carry both ids into `audit.llm_calls` (D9).
    bind_conversation_id(str(conversation_id))
    bind_turn_id(str(turn_id))
    try:
        ctx = registry.build_tool_context(session, conversation_id, trace_id)
        audit = registry.audit_recorder_for(ctx, turn_id)
        tools, write_tools = registry.turn_tools(ctx, session, audit)

        async def _record(
            event_type: AuditType, payload: dict[str, JsonValue], sources: Sequence[str] = ()
        ) -> None:
            """Best effort (D15): a runner-level audit event's recording
            failure is logged and never fails the turn -- only a failed
            `tool_call` audit inside a read or write blocks that call itself
            (`registry.RecordingBankTools`, `ConfirmedWriteTools`)."""
            try:
                await audit.record(event_type, payload, sources)
            except Exception:
                _logger.warning(
                    "audit.write_failed",
                    conversation_id=str(conversation_id),
                    turn_id=str(turn_id),
                    trace_id=trace_id,
                    type=event_type,
                )

        config: RunnableConfig = {
            "configurable": {
                "thread_id": str(conversation_id),
                "session": ctx,
                "bank_tools": tools,
                "llm": host.llm,
                "bank_write_tools": write_tools,
                "vault": vault,
                "handoff_tools": ServiceHandoffTools(ctx),
                "audit": audit,
                "classifier": host.classifier,
                # Session-bound: the handoff summary reads the masked transcript (D1).
                "transcript": functools.partial(store.list_messages, conversation_id),
            }
        }

        route_taken: str | None = None
        nlu: NLUResult | None = None
        language: Literal["es", "pt"] = "es"
        reply = ""
        ui: list[UIEvent] = []
        handed_off = False
        # Any node reporting `degraded` (classifier-served NLU or baseline
        # text) marks the whole turn (ADR-032).
        degraded = False
        nlu_degraded = False
        # `path` of `reply_sent`: "agent" when the agent node ran and `understand`
        # did not (a pass or a degraded agent turn falls through to the pipeline).
        agent_ran = False
        agent_plan_ran = False
        understand_ran = False

        grounding_outcome: str | None = None
        # This turn's fact provenance (`Fact.source`), recorded on
        # `reply_sent` so the staff timeline's "why" lists sources (D7-A D20).
        fact_sources: list[str] = []
        # Per-intent record of the turn (analytics D14): each node update carries
        # only its own delta, and `load_session`'s reset marker streams as `[]`.
        intent_segments: list[JsonValue] = []
        with fact_values.collecting() as collected_values:
            graph_input: TurnInput = {
                "user_text": graph_text or "",
                "confirmation": confirmation,
                "resume": resume,
                "selection": selection,
                "card_selection": card_selection,
            }
            seed = await _introduced_seed(host.graph, config, conversation_id)
            if seed.get("introduced"):
                graph_input["introduced"] = True
            if "history" in seed:
                graph_input["history"] = seed["history"]
            async for update in host.graph.astream(
                graph_input,
                config=config,
                stream_mode="updates",
            ):
                for node_name, values in update.items():
                    await events.publish(conversation_id, "status", {"step": node_name})
                    if node_name == "relay_to_agent":
                        # Human mode (D13): echo the typed text for the agent and
                        # stop. Checked before the `None` guard because this node
                        # returns an empty update. The customer message was
                        # persisted by `start_turn`.
                        await events.publish(
                            conversation_id, "message", {"role": "customer", "text": text or ""}
                        )
                        await events.publish(conversation_id, "done", {"turn_id": str(turn_id)})
                        return
                    # A node whose returned update is empty (e.g. `next_intent`
                    # with nothing left to pop) streams as `None`, not `{}`.
                    if values is None:
                        continue
                    if values.get("degraded"):
                        degraded = True
                    if node_name == "handoff" and values.get("handoff_id") is not None:
                        handed_off = True
                    if node_name == "agent_plan":
                        # A button turn (Acepto / No acepto, or a stale click). It
                        # carries no labels: `agent` follows with them, or the turn
                        # ends in `finish` / `handoff` (see after the loop).
                        agent_ran = True
                        agent_plan_ran = True
                    elif node_name == "agent":
                        agent_ran = True
                        labels = values.get("agent_labels")
                        if labels:
                            language = (
                                labels["language"]
                                if labels["language"] in ("es", "pt")
                                else language
                            )
                            await _record(
                                "nlu_result",
                                {
                                    "language": labels["language"],
                                    "status": labels["status"],
                                    "intents": list(labels["intents"]),
                                    "source": "agent",
                                },
                            )
                            if route_taken is None:
                                route_taken = labels["route"]
                    elif node_name == "understand":
                        understand_ran = True
                        nlu = values.get("nlu")
                        nlu_degraded = bool(values.get("degraded"))
                        language = values.get("language", language)
                        if nlu is not None:
                            await _record(
                                "nlu_result",
                                {
                                    "language": language,
                                    "status": nlu.status,
                                    "intents": [intent for intent in nlu.intents],
                                    **_nlu_source(nlu_degraded, host),
                                },
                            )
                    elif route_taken is None and node_name in _BRANCH_NODES:
                        route_taken = node_name
                    fact_sources.extend(fact.source for fact in values.get("facts") or [])
                    intent_segments.extend(values.get("intent_segments") or [])
                    reply_value = values.get("reply")
                    if reply_value is not None:
                        reply = reply_value
                    ui_value = values.get("ui")
                    if ui_value is not None:
                        ui = ui_value
                    escalation_reason = values.get("escalation_reason")
                    if escalation_reason is not None:
                        await _record("rule_hit", {"rule_id": escalation_reason})
                if node_name in ("compose", "agent"):
                    outcome = (values or {}).get("grounding")
                    if outcome is not None:
                        # Worst of the turn (D32); the channel is last-write-wins.
                        grounding_outcome = _worse_grounding(grounding_outcome, outcome)

        if agent_ran and handed_off:
            route_taken = "handoff"
        elif agent_plan_ran and route_taken is None:
            # Stale click (old token): `agent_plan` -> `finish`, no labels. The
            # plan is a card-block plan, so the turn is recorded as that route.
            route_taken = "card_block"

        for event in ui:
            await events.publish(conversation_id, "ui", event.model_dump(mode="json"))
        if handed_off:
            await events.publish(
                conversation_id, "mode", {"mode": "human", "agent_display_name": None}
            )

        # The graph's reply carries tokens; the customer sees the real values
        # (D4). Flush first so tokens minted this turn (`put_address`) resolve.
        await vault.flush()
        masked_reply = reply
        reply = await vault.unmask(reply)

        ui_payload = [event.model_dump(mode="json") for event in ui] if ui else None
        await store.add_message(
            conversation_id,
            turn_id,
            role="bot",
            content=reply,
            content_masked=masked_reply,
            ui_payload=ui_payload,
        )
        await _record(
            "reply_sent",
            {
                "route": route_taken or "fallback",
                "path": "agent" if agent_ran and not understand_ran else "pipeline",
                "ui_kinds": [event.kind for event in ui],
                "length": len(reply),
                "degraded": degraded,
                "segments": intent_segments,
                # Deduplicated in order; only code-written values, never raw PII.
                "fact_values": list(dict.fromkeys(collected_values)),
                **({"grounding": {"outcome": grounding_outcome}} if grounding_outcome else {}),
            },
            list(dict.fromkeys(fact_sources)),
        )
        trace.get_current_span().set_attribute("cardy.degraded", degraded)
        await events.publish(
            conversation_id, "message", {"role": "bot", "text": reply, "sources": []}
        )
        if any(event.kind == "conversation_closed" for event in ui):
            await store.close_conversation(conversation_id)

        if get_settings().app_env != "prod":
            final_state = await host.graph.aget_state(config)
            pending = final_state.values.get("pending")
            debug = DebugInfo(
                # A pick turn skips NLU; the checkpointed language is the truth.
                language=final_state.values.get("language", language),
                status=nlu.status if nlu is not None else None,
                intents=nlu.intents if nlu is not None else [],
                slots=nlu.slots if nlu is not None else NLUSlots(),
                route=route_taken or "fallback",
                tools_called=tools.calls,
                pending=f"{pending['flow']}.{pending['awaiting_slot']}" if pending else None,
                ui=[event.kind for event in ui],
                # The same per-turn value `reply_sent` and `cardy.degraded` carry.
                degraded=degraded,
            )
            await events.publish(conversation_id, "debug", debug.model_dump(mode="json"))

        await events.publish(conversation_id, "done", {"turn_id": str(turn_id)})
    except Exception as exc:
        # No user text and no PII: only ids and the exception's class name.
        _logger.warning(
            "turn.failed",
            conversation_id=str(conversation_id),
            trace_id=trace_id,
            turn_id=str(turn_id),
            error_type=type(exc).__name__,
        )
        await events.publish(conversation_id, "error", {"code": "turn_failed"})
        await events.publish(conversation_id, "done", {"turn_id": str(turn_id)})
    finally:
        await get_redis().eval(_RELEASE_LOCK_SCRIPT, 1, lock_key, str(turn_id))
