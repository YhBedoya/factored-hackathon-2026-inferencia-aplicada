"""Pure analytics rules: occurrences, interaction outcome and the finish rule.

No SQL, no I/O, no LLM and no `conversation` import: the per-intent segments
arrive as plain dicts from the `reply_sent` audit payload (spec D12). The
worker reads rows and calls these functions.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

# Bump when a rule below changes what a stored row means (REQ-R3).
METRICS_VERSION = 1

# Occurrence outcome from the last segment status (spec D2).
_OUTCOME_BY_STATUS = {
    "resolved": "resolved",
    "handoff": "handoff",
    "abstained": "abstained",
    "cancelled": "cancelled",
    "awaiting": "abandoned",
}

# Slots that wait on the customer's yes/no or code, not on missing information (D17).
_NON_CLARIFYING_SLOTS = frozenset({"confirmation", "otp"})

_OPEN_HANDOFF = frozenset({"queued", "claimed"})


@dataclass(frozen=True)
class Occurrence:
    seq: int
    intent: str
    outcome: str
    needed_clarification: bool
    turns: int
    bot_offered: bool


@dataclass(frozen=True)
class InteractionOutcome:
    real_intent_count: int
    resolved: bool | None
    abandoned: bool
    abstained: bool


def build_occurrences(
    turn_segments: Sequence[Sequence[Mapping[str, Any]]],
) -> list[Occurrence]:
    """Fold per-turn segments into occurrences (D5).

    `turn_segments` holds one list per `reply_sent`, in time order. A segment
    continues the previous occurrence only when it has the same intent and
    that occurrence's last status is `awaiting`; any other status closes it.
    """
    # Mutable working rows: [intent, last_status, clarified, turns, bot_offered].
    rows: list[list[Any]] = []
    for segments in turn_segments:
        counted_this_turn: set[int] = set()
        for seg in segments:
            intent = str(seg["intent"])
            status = str(seg["status"])
            if rows and rows[-1][0] == intent and rows[-1][1] == "awaiting":
                row = rows[-1]
            else:
                row = [intent, status, False, 0, False]
                rows.append(row)
            row[1] = status
            slot = seg.get("awaiting_slot")
            if status == "awaiting" and slot and slot not in _NON_CLARIFYING_SLOTS:
                row[2] = True
            if seg.get("bot_offered"):
                row[4] = True
            # `turns` counts reply_sent entries, so two segments of one turn count once.
            if id(row) not in counted_this_turn:
                counted_this_turn.add(id(row))
                row[3] += 1
    return [
        Occurrence(
            seq=i,
            intent=r[0],
            outcome=_OUTCOME_BY_STATUS.get(r[1], "abstained"),
            needed_clarification=r[2],
            turns=r[3],
            bot_offered=r[4],
        )
        for i, r in enumerate(rows, start=1)
    ]


def interaction_outcome(
    occurrences: Sequence[Occurrence],
    *,
    end_reason: str,
    handoff_count: int,
    any_abstain_route: bool,
) -> InteractionOutcome:
    """Interaction-level flags (D4, D6, D22)."""
    # A declined bot offer is not a real intent (D22); in any other outcome it counts.
    counted = [o for o in occurrences if not (o.bot_offered and o.outcome == "cancelled")]
    resolved: bool | None = None
    if counted:
        resolved = handoff_count == 0 and all(o.outcome == "resolved" for o in counted)
    return InteractionOutcome(
        real_intent_count=len(counted),
        resolved=resolved,
        abandoned=(
            end_reason == "idle" and bool(occurrences) and occurrences[-1].outcome == "abandoned"
        ),
        abstained=any_abstain_route or any(o.outcome == "abstained" for o in occurrences),
    )


def finish_reason(
    *,
    status: str,
    last_message_at: datetime,
    handoff_statuses: Sequence[str],
    now: datetime,
    idle_minutes: int,
) -> str | None:
    """The `end_reason` when the conversation is finished, else `None` (REQ-R3).

    `handoff_statuses` is in creation order. An open handoff (`queued` or
    `claimed`) is never finished, even if the customer closed the chat.
    """
    if any(s in _OPEN_HANDOFF for s in handoff_statuses):
        return None
    if status == "closed":
        return "customer_closed"
    if now - last_message_at >= timedelta(minutes=idle_minutes):
        if handoff_statuses and handoff_statuses[-1] == "returned":
            return "handoff_returned"
        return "idle"
    return None
