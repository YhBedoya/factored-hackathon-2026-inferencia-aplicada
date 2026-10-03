"""Deterministic mock interactions for the analytics fact tables (REQ-R5, spec D15).

Pure functions: no SQL, no LLM call and no clock. The day's date seeds a local
`random.Random` and ids are `uuid5`, so the same day always gives the same rows.
Rows are labelled `source = "mock"`. The profile (`mock_profile.yaml`) is
team-generated synthetic data and makes no claim about a trend.

The core intents are listed in the profile, not imported from the conversation
domain, because analytics must not depend on it.
"""

from __future__ import annotations

import math
import random
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta, tzinfo
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml

_PROFILE_PATH = Path(__file__).with_name("mock_profile.yaml")
# Fixed namespace so ids never change between runs or machines.
_NAMESPACE = uuid.UUID("5b0f6c1e-7d3a-4c52-9a41-2f8e6b0d9c37")
_SENTIMENTS = ("negative", "neutral", "positive")


@dataclass(frozen=True)
class MockIntent:
    """One `analytics.interaction_intents` row; field names are the columns."""

    conversation_id: str
    seq: int
    intent: str
    outcome: str
    needed_clarification: bool
    turns: int
    bot_offered: bool = False


@dataclass(frozen=True)
class MockInteraction:
    """One `analytics.interactions` row (field names are the columns) plus its intent rows."""

    conversation_id: str
    source: str
    started_at: datetime
    ended_at: datetime
    end_reason: str
    duration_s: int
    language: str
    country: str
    channel: str
    customer_messages: int
    bot_messages: int
    agent_messages: int
    turns: int
    real_intent_count: int
    resolved: bool | None
    abandoned: bool
    abstained: bool
    degraded: bool
    escalated: bool
    handoff_count: int
    handoff_queue: str | None
    handoff_reason: str | None
    handoff_cause_group: str | None
    time_to_claim_s: int | None
    cost_usd: Decimal
    cost_nlu_usd: Decimal
    cost_compose_usd: Decimal
    cost_handoff_summary_usd: Decimal
    cost_agent_usd: Decimal
    served_by: str
    llm_call_count: int
    sentiment_overall: str
    sentiment_start: str
    sentiment_end: str
    sentiment_model: str
    sentiment_prompt_version: str
    sentiment_cost_usd: Decimal
    sentiment_scored_at: datetime
    computed_at: datetime
    metrics_version: int
    intents: list[MockIntent] = field(default_factory=list)


def load_profile() -> dict[str, Any]:
    """Read `mock_profile.yaml`."""
    with _PROFILE_PATH.open(encoding="utf-8") as fh:
        profile: dict[str, Any] = yaml.safe_load(fh)
    return profile


def generate_day(day: date, profile: dict[str, Any], tz: tzinfo) -> list[MockInteraction]:
    """All mock interactions whose local day in `tz` is `day`, ordered by `ended_at`."""
    rng = random.Random(day.isoformat())
    vol = profile["volume"]
    base = vol["weekday"] if day.weekday() < 5 else vol["weekend"]
    count = round(base * (1 + rng.uniform(-vol["noise"], vol["noise"])))

    day_start = datetime.combine(day, time.min, tzinfo=tz).astimezone(UTC)
    day_end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=tz).astimezone(UTC)
    day_seconds = int((day_end - day_start).total_seconds())

    rows = [
        _interaction(rng, profile, f"{day.isoformat()}:{i}", day_start, day_seconds, tz)
        for i in range(count)
    ]
    rows.sort(key=lambda r: r.ended_at)
    return rows


def _weighted[T](rng: random.Random, options: dict[T, float]) -> T:
    return rng.choices(list(options), weights=list(options.values()))[0]


def _money(value: float) -> Decimal:
    return Decimal(f"{value:.6f}")


def _start_second(rng: random.Random, vol: dict[str, Any], day_seconds: int) -> int:
    """Seconds into the local day: a flat base plus the two peaks."""
    if rng.random() < vol["base_share"]:
        return rng.randrange(day_seconds)
    peaks = vol["peaks"]
    peak = rng.choices(peaks, weights=[p["weight"] for p in peaks])[0]
    minute = rng.gauss(peak["mean_min"], peak["sd_min"])
    return min(max(int(minute * 60), 0), day_seconds - 1)


def _sentiment(
    rng: random.Random, cfg: dict[str, Any], customer_messages: int
) -> tuple[str, str, str]:
    """(overall, start, end): a trajectory is drawn, then fitted around the overall label."""
    overall = _weighted(rng, cfg["overall"])
    draw = rng.random()
    # One customer message has nothing to compare: start and end match (REQ-R4.4).
    if customer_messages == 1 or draw >= cfg["end_better"] + cfg["end_worse"]:
        return overall, overall, overall
    i = _SENTIMENTS.index(overall)
    if draw < cfg["end_better"]:
        end = max(i, 1)
        return overall, _SENTIMENTS[end - 1], _SENTIMENTS[end]
    start = min(i, 1) + 1
    return overall, _SENTIMENTS[start], _SENTIMENTS[start - 1]


def _pick_intents(rng: random.Random, profile: dict[str, Any], reason: str | None) -> list[str]:
    """Intent names for one interaction. A forced intent comes first."""
    count = _weighted(rng, profile["intent_count"])
    names: list[str] = []
    if reason == "human_request":
        names.append("human_request")
    elif reason == "suspected_fraud":
        names.append("unrecognized_charge")
    # human_request is always a handoff, so it only appears with that cause.
    weights = {
        name: v["weight"]
        * (profile["unrecognized_charge_outside_fraud"] if name == "unrecognized_charge" else 1)
        for name, v in profile["intents"].items()
        if name != "human_request"
    }
    while len(names) < count:
        names.append(_weighted(rng, weights))
    return names


def _interaction(
    rng: random.Random,
    profile: dict[str, Any],
    key: str,
    day_start: datetime,
    day_seconds: int,
    tz: tzinfo,
) -> MockInteraction:
    cid = str(uuid.uuid5(_NAMESPACE, key))
    outcome = _weighted(rng, profile["outcomes"])

    group: str | None = None
    reason: str | None = None
    queue: str | None = None
    if outcome == "escalated":
        group = _weighted(rng, profile["escalation_causes"])
        reason = rng.choice(list(profile["escalation_reasons"][group]))
        queue = profile["escalation_reasons"][group][reason]

    names = _pick_intents(rng, profile, reason)
    n = len(names)

    # Which occurrence carries the non-resolved ending: the forced one for the
    # handoffs that name an intent, the last one when abandoned (it was still
    # waiting), otherwise weighted by (1 - resolve rate).
    fail = 0
    if outcome == "abandoned":
        fail = n - 1
    elif outcome != "resolved" and reason not in ("human_request", "suspected_fraud"):
        weights = [1.01 - profile["intents"][x]["resolve"] for x in names]
        fail = rng.choices(range(n), weights=weights)[0]
    ending = {"escalated": "handoff", "abandoned": "abandoned", "abstained": "abstained"}.get(
        outcome
    )

    # Messages: customer and bot alternate, agent messages only after a handoff.
    msg = profile["messages"]
    total = round(rng.lognormvariate(math.log(msg["median"]), msg["sigma"]))
    total = min(max(total, msg["min"], 2 * n), msg["max"])
    agent = 0
    if outcome == "escalated":
        agent = max(min(rng.randint(1, msg["agent_max"]), total - 2), 0)
    customer = max((total - agent + 1) // 2, 1)
    bot = max(total - agent - customer, 0)
    turns = customer

    per_intent = [turns // n + (1 if i < turns % n else 0) for i in range(n)]
    intents = [
        MockIntent(
            conversation_id=cid,
            seq=i,
            intent=name,
            outcome=ending if (ending and i == fail) else "resolved",
            needed_clarification=rng.random() < profile["needed_clarification"],
            turns=per_intent[i],
        )
        for i, name in enumerate(names)
    ]

    # Time: start from the two-peak mixture, never past the local day's end.
    stp = profile["seconds_per_turn"]
    duration = turns * rng.randint(stp["min"], stp["max"]) + (rng.randint(60, 600) if agent else 0)
    start_s = _start_second(rng, profile["volume"], day_seconds)
    duration = min(duration, day_seconds - 1 - start_s)
    started = (day_start + timedelta(seconds=start_s)).astimezone(tz)
    ended = (day_start + timedelta(seconds=start_s + duration)).astimezone(tz)

    if outcome == "escalated":
        end_reason = "handoff_returned"
    elif outcome == "abandoned":
        end_reason = "idle"
    else:
        end_reason = _weighted(rng, profile["end_reason"][outcome])

    unit = profile["unit_cost_usd"]
    nlu = unit["nlu"] * turns
    compose = unit["compose"] * turns
    summary = unit["handoff_summary"] if outcome == "escalated" else 0.0

    overall, s_start, s_end = _sentiment(rng, profile["sentiment"], customer)

    handoffs = 0
    claim = None
    if outcome == "escalated":
        handoffs = 2 if rng.random() < profile["second_handoff_share"] else 1
        claim = rng.randint(profile["time_to_claim_s"]["min"], profile["time_to_claim_s"]["max"])

    return MockInteraction(
        conversation_id=cid,
        source="mock",
        started_at=started,
        ended_at=ended,
        end_reason=end_reason,
        duration_s=duration,
        language=_weighted(rng, profile["language"]),
        country=_weighted(rng, profile["country"]),
        channel=profile["channel"],
        customer_messages=customer,
        bot_messages=bot,
        agent_messages=agent,
        turns=turns,
        real_intent_count=len(intents),
        # D6: every occurrence resolved and no handoff (the mock has no cancelled).
        resolved=all(i.outcome == "resolved" for i in intents) and handoffs == 0,
        abandoned=end_reason == "idle" and intents[-1].outcome == "abandoned",
        abstained=any(i.outcome == "abstained" for i in intents),
        degraded=rng.random() < profile["degraded_share"],
        escalated=outcome == "escalated",
        handoff_count=handoffs,
        handoff_queue=queue,
        handoff_reason=reason,
        handoff_cause_group=group,
        time_to_claim_s=claim,
        cost_usd=_money(nlu + compose + summary),
        cost_nlu_usd=_money(nlu),
        cost_compose_usd=_money(compose),
        cost_handoff_summary_usd=_money(summary),
        cost_agent_usd=Decimal("0"),
        served_by="pipeline",
        llm_call_count=2 * turns + (1 if outcome == "escalated" else 0),
        sentiment_overall=overall,
        sentiment_start=s_start,
        sentiment_end=s_end,
        sentiment_model=profile["sentiment"]["model"],
        sentiment_prompt_version=profile["sentiment"]["prompt_version"],
        sentiment_cost_usd=Decimal("0"),
        sentiment_scored_at=ended,
        computed_at=ended,
        metrics_version=profile["metrics_version"],
        intents=intents,
    )
