"""Staff conversation list and per-conversation timeline (D7-A D16-D20).

Read-only and masked: turn text comes from `app.messages.content_masked` and
the ledger rows are projected without `input_text`/`output_json` (D17). The
outcome (D18) is computed here from the facts `repository` returns, so its
precedence lives in exactly one place, list filter and summary alike.
"""

from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Literal, cast
from uuid import UUID

from app.core.errors import NotFound
from app.core.llm.settings import LLMSettings
from app.domains.audit import repository
from app.domains.audit.schemas import (
    AuditType,
    ConversationPage,
    ConversationSummary,
    ConversationTimeline,
    LLMCallView,
    TimelineEvent,
    TurnTimeline,
)
from app.domains.customers.service import COUNTRY_LABELS

__all__ = ["compute_outcome", "get_timeline", "list_conversations"]

_MAX_LIMIT = 200


def compute_outcome(
    *,
    has_reply: bool,
    handoff_queue: str | None,
    reply_route: str | None,
    reply_ui_kinds: Sequence[str],
    nlu_status: str | None,
) -> str | None:
    """D18 precedence, same as `eval/harness/checks.py::outcome()`.

    `card_picker` and an `ambiguous` NLU status are the server-side stand-in
    for the harness's `pending` check. A handoff wins even without a
    `reply_sent` (human decision); no handoff and no reply means no outcome.
    """
    if handoff_queue is not None:
        return f"handoff:{handoff_queue}"
    if not has_reply:
        return None
    if reply_route == "abstain":
        return "abstained"
    if nlu_status == "ambiguous" or "card_picker" in reply_ui_kinds:
        return "clarified"
    return "resolved"


def _country_code(label: str | None) -> Literal["MX", "CO", "AR"] | None:
    return COUNTRY_LABELS.get(label) if label is not None else None


def _summary(
    facts: Mapping[str, Any], intents: list[str], turns: int
) -> tuple[ConversationSummary, str | None]:
    outcome = compute_outcome(
        has_reply=facts["has_reply"],
        handoff_queue=facts["handoff_queue"],
        reply_route=facts["reply_route"],
        reply_ui_kinds=facts["reply_ui_kinds"],
        nlu_status=facts["nlu_status"],
    )
    summary = ConversationSummary(
        conversation_id=facts["id"],
        created_at=facts["started_at"],
        language=facts["language"],
        country=_country_code(facts["country_label"]),
        intents=intents,
        outcome=outcome,
        escalated=facts["handoff_queue"] is not None,
        queue=facts["handoff_queue"],
        mode=facts["mode"],
        status=facts["status"],
        turns=turns,
    )
    return summary, outcome


def _matches_outcome(outcome: str | None, wanted: str) -> bool:
    if outcome is None:
        return False
    return outcome.startswith("handoff:") if wanted == "handoff" else outcome == wanted


async def list_conversations(
    *,
    language: str | None = None,
    country: str | None = None,
    intent: str | None = None,
    outcome: str | None = None,
    escalation: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = 50,
    offset: int = 0,
) -> ConversationPage:
    """D19: ANDed filters, newest first, `total` counts every match. The date
    filter is on `started_at`, inclusive of both UTC days (human decision Q1).
    """
    if not 1 <= limit <= _MAX_LIMIT or offset < 0:
        raise ValueError(f"limit must be 1..{_MAX_LIMIT} and offset >= 0")
    countries = (
        [label for label, code in COUNTRY_LABELS.items() if code == country]
        if country is not None
        else None
    )
    facts = await repository.fetch_conversation_facts(
        language=language,
        countries=countries,
        intent=intent,
        escalation=escalation,
        date_from=datetime.combine(date_from, time.min, tzinfo=UTC) if date_from else None,
        date_to_exclusive=(
            datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=UTC) if date_to else None
        ),
    )
    if outcome is not None:
        facts = [row for row in facts if _matches_outcome(_summary(row, [], 0)[1], outcome)]
    page = facts[offset : offset + limit]
    intents, turns = await repository.fetch_conversation_rollups([row["id"] for row in page])
    return ConversationPage(
        total=len(facts),
        items=[
            _summary(row, intents.get(row["id"], []), turns.get(row["id"], 0))[0] for row in page
        ],
    )


def _event(row: Mapping[str, Any]) -> TimelineEvent:
    return TimelineEvent(
        at=row["at"],
        type=cast(AuditType, row["type"]),
        actor=row["actor"],
        payload=row["payload"],
        sources=list(row["sources"] or []),
    )


def _call_view(row: Mapping[str, Any]) -> LLMCallView:
    return LLMCallView(
        step=row["step"],
        model_id=row["model_id"],
        prompt_version=row["prompt_version"],
        temperature=None if row["temperature"] is None else float(row["temperature"]),
        attempt=row["attempt"],
        status=row["status"],
        latency_ms=float(row["latency_ms"]),
        input_tokens=row["input_tokens"],
        output_tokens=row["output_tokens"],
        cost_usd=None if row["cost_usd"] is None else float(row["cost_usd"]),
    )


def _langfuse_url(calls: Sequence[Mapping[str, Any]]) -> str | None:
    """D20: from the ledger rows, since `audit_events.langfuse_trace_id` is
    always NULL. `null` without a configured host or a trace id.
    """
    host = LLMSettings().langfuse_host
    trace_id = next((c["langfuse_trace_id"] for c in calls if c["langfuse_trace_id"]), None)
    if not host or trace_id is None:
        return None
    return f"{host.rstrip('/')}/trace/{trace_id}"


def _assemble_turn(
    turn_id: UUID,
    messages: Sequence[Mapping[str, Any]],
    events: Sequence[TimelineEvent],
    event_rows: Sequence[Mapping[str, Any]],
    calls: Sequence[Mapping[str, Any]],
) -> TurnTimeline:
    customer = next((m for m in messages if m["role"] == "customer"), None)
    bot = next((m for m in reversed(messages) if m["role"] == "bot"), None)
    reply = next((e for e in reversed(events) if e.type == "reply_sent"), None)
    nlu = next((e.payload for e in reversed(events) if e.type == "nlu_result"), None)
    sources = list(dict.fromkeys(s for e in events for s in e.sources))
    costs = [c["cost_usd"] for c in calls if c["cost_usd"] is not None]
    latency = (
        (reply.at - customer["created_at"]).total_seconds() * 1000
        if reply is not None and customer is not None
        else None
    )
    starts = [m["created_at"] for m in messages] + [e.at for e in events]
    return TurnTimeline(
        turn_id=turn_id,
        started_at=min(starts),
        customer_text_masked=customer["content_masked"] if customer else None,
        bot_text_masked=bot["content_masked"] if bot else None,
        nlu=nlu,
        rules=[e for e in events if e.type == "rule_hit"],
        tools=[e for e in events if e.type in ("tool_call", "tool_result")],
        events=list(events),
        sources=sources,
        policy_version=event_rows[0]["policy_version"] if event_rows else None,
        llm_calls=[_call_view(c) for c in calls],
        latency_ms=latency,
        cost_usd=float(sum(costs)) if costs else None,
        langfuse_url=_langfuse_url(calls),
    )


async def get_timeline(conversation_id: UUID) -> ConversationTimeline:
    """The conversation's turns in order. Raises `NotFound` for an unknown id.

    A turn is the messages and audit events sharing a `turn_id`; rows with no
    `turn_id` (conversation-level events) belong to no turn and are skipped.
    """
    facts = await repository.fetch_conversation_facts(conversation_id=conversation_id)
    if not facts:
        raise NotFound("conversation not found")
    messages = await repository.fetch_messages(conversation_id)
    event_rows = await repository.fetch_events(conversation_id)
    calls = await repository.fetch_llm_calls(conversation_id)

    turn_ids = list(
        dict.fromkeys(
            row["turn_id"]
            for row in sorted(
                [*messages, *event_rows],
                key=lambda r: r.get("created_at") or r["at"],
            )
            if row["turn_id"] is not None
        )
    )
    turns = []
    for turn_id in turn_ids:
        turn_event_rows = [r for r in event_rows if r["turn_id"] == turn_id]
        turns.append(
            _assemble_turn(
                turn_id,
                [m for m in messages if m["turn_id"] == turn_id],
                [_event(r) for r in turn_event_rows],
                turn_event_rows,
                [c for c in calls if c["turn_id"] == turn_id],
            )
        )
    turns.sort(key=lambda t: t.started_at)
    intents, turn_counts = await repository.fetch_conversation_rollups([conversation_id])
    summary, _ = _summary(
        facts[0], intents.get(conversation_id, []), turn_counts.get(conversation_id, 0)
    )
    return ConversationTimeline(conversation=summary, turns=turns)
