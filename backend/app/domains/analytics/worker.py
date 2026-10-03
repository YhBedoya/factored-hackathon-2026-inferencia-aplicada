"""The analytics worker: one pass, the loop and the CLI (ADR-033, REQ-R3..R6).

`run_pass` finds conversations with activity since the watermark, computes the
finished ones into `analytics.interactions` / `interaction_intents` (D7, D9,
D10), seeds mock days when enabled (D15), then scores sentiment on masked
customer text, one conversation at a time (D13, D16). Everything it needs from
Postgres goes through the `AnalyticsStore` protocol, so the rules here run
against an in-memory fake; `repository.PostgresAnalyticsStore` (T11) is the
real one.

The worker runs as its own database role (D8) and imports nothing from the
conversation domain (D12). Its engine comes from
`ANALYTICS_DATABASE_URL` only: an empty value, a URL without a password or an
eval database is a start-up error, never a fallback to `DATABASE_URL`.

Logs carry fields only (counts, ids, exception class), never message text.
"""

import argparse
import asyncio
import importlib
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, Protocol
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError

from app.core.config import Settings, get_settings
from app.core.llm import LLMCallRecord
from app.core.logging import configure_logging
from app.core.telemetry import setup_log_export
from app.domains.analytics.cause_groups import cause_group
from app.domains.analytics.mock import MockInteraction, generate_day, load_profile
from app.domains.analytics.sentiment import HaikuSentimentScorer, SentimentResult, SentimentScorer
from app.domains.analytics.service import (
    METRICS_VERSION,
    Occurrence,
    build_occurrences,
    finish_reason,
    interaction_outcome,
)
from app.domains.customers.service import COUNTRY_LABELS

__all__ = [
    "AnalyticsStore",
    "ConversationFacts",
    "HandoffFact",
    "InteractionRow",
    "MessageFact",
    "PassStats",
    "ReplyFact",
    "ScoringTarget",
    "StepCost",
    "WorkerConfigError",
    "WorkerState",
    "main",
    "run_pass",
    "run_recompute",
    "run_rescore_sentiment",
]

_logger = structlog.get_logger()

# A pass scores at most this many rows, so one slow provider never stalls the
# compute step of the next pass (REQ-R6.2: one call at a time, bounded work).
_SCORE_BATCH = 50
_EVAL_DB_PREFIX = "latam_eval_"
_SENTIMENT_STEP = "sentiment"


class WorkerConfigError(Exception):
    """A start-up error: the worker refuses to run (never carries a URL)."""


# --- the facts the store hands over: masked text only, no customer id (R5, D11) ---


@dataclass(frozen=True)
class MessageFact:
    """One message. Only `content_masked` exists here: raw text never leaves the store."""

    role: str  # customer | bot | agent
    turn_id: str | None
    created_at: datetime
    content_masked: str | None


@dataclass(frozen=True)
class ReplyFact:
    """One `reply_sent` audit payload, in time order."""

    route: str | None
    degraded: bool
    segments: Sequence[dict[str, Any]]


@dataclass(frozen=True)
class HandoffFact:
    """One `app.handoffs` row, in creation order."""

    queue: str
    reason: str
    status: str
    created_at: datetime
    claimed_at: datetime | None


@dataclass(frozen=True)
class StepCost:
    """`audit.llm_calls` rows of one step: summed cost (nulls as 0) and row count."""

    cost_usd: Decimal
    calls: int


@dataclass(frozen=True)
class ConversationFacts:
    conversation_id: str
    status: str
    language: str | None
    channel: str | None
    country_label: str | None  # `bank.customers.country`, joined by the store, id not kept
    messages: Sequence[MessageFact]  # oldest first
    replies: Sequence[ReplyFact]  # oldest first
    handoffs: Sequence[HandoffFact]  # oldest first
    step_costs: dict[str, StepCost]  # includes `sentiment`; the worker leaves it out


@dataclass(frozen=True)
class WorkerState:
    watermark: datetime | None
    mock_seeded_through: date | None


@dataclass(frozen=True)
class ScoringTarget:
    conversation_id: str
    language: str | None


@dataclass(frozen=True)
class InteractionRow:
    """`analytics.interactions` minus the sentiment columns (`set_sentiment` owns those)."""

    conversation_id: str
    source: str
    started_at: datetime
    ended_at: datetime
    end_reason: str
    duration_s: int
    language: str | None
    country: str | None
    channel: str | None
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
    llm_call_count: int
    computed_at: datetime
    metrics_version: int


class AnalyticsStore(Protocol):
    """Everything a pass needs from the database. Ids are UUID strings."""

    async def get_state(self) -> WorkerState: ...

    async def set_watermark(self, watermark: datetime) -> None: ...

    async def set_mock_seeded_through(self, day: date) -> None: ...

    async def list_candidates(self, since: datetime | None) -> list[str]:
        """Conversations with message, handoff or close activity at or after `since`.

        `None` means every conversation, once (first run). D7: from
        `app.messages(created_at)` and the handoff time columns, not a scan of
        `app.conversations`.
        """
        ...

    async def load_facts(self, conversation_id: str) -> ConversationFacts | None:
        """The conversation's facts (masked text only), or `None` if it is gone."""
        ...

    async def upsert_interaction(self, row: InteractionRow, intents: Sequence[Occurrence]) -> None:
        """Upsert by `conversation_id` and replace its intent rows, in one transaction.

        On conflict the sentiment columns are kept, so a recompute keeps them,
        unless a customer message is newer than `sentiment_scored_at`: then they
        are cleared and a later pass re-scores the row. `source` is always `real`.
        """
        ...

    async def insert_mock(self, rows: Sequence[MockInteraction]) -> None:
        """Insert mock rows and their intents; an existing id is left alone."""
        ...

    async def list_scoring_targets(
        self, *, all_real: bool, limit: int | None
    ) -> list[ScoringTarget]:
        """Real rows to score, newest `ended_at` first.

        `all_real=False`: only rows with null sentiment and at least one
        customer message. `all_real=True`: every real row (re-score).
        """
        ...

    async def customer_messages(self, conversation_id: str) -> list[str]:
        """The customer's `content_masked` texts in order; never raw `content`."""
        ...

    async def set_sentiment(
        self, conversation_id: str, result: SentimentResult, scored_at: datetime
    ) -> None: ...

    async def list_stale(self, metrics_version: int) -> list[str]:
        """Real rows with `metrics_version` below the given one."""
        ...

    async def record_llm_call(self, call: LLMCallRecord) -> None:
        """Write one `audit.llm_calls` row with the worker's own role (D8)."""
        ...


@dataclass(frozen=True)
class PassStats:
    written: int = 0
    mock_days: int = 0
    scored: int = 0
    sentiment_unavailable: bool = False


class _LedgerSink:
    """`LLMCallSink` that writes the ledger through the store (not `AuditLLMCallSink`)."""

    def __init__(self, store: AnalyticsStore) -> None:
        self._store = store

    async def record(self, call: LLMCallRecord) -> None:
        await self._store.record_llm_call(call)


# --- the pure compute step -------------------------------------------------------


def compute_interaction(
    facts: ConversationFacts, *, now: datetime, idle_minutes: int
) -> tuple[InteractionRow, list[Occurrence]] | None:
    """The row and intents for a finished conversation, `None` while it is not finished."""
    if not facts.messages:
        return None
    started_at = facts.messages[0].created_at
    ended_at = facts.messages[-1].created_at
    end_reason = finish_reason(
        status=facts.status,
        last_message_at=ended_at,
        handoff_statuses=[h.status for h in facts.handoffs],
        now=now,
        idle_minutes=idle_minutes,
    )
    if end_reason is None:
        return None

    roles = [m.role for m in facts.messages]
    occurrences = build_occurrences([r.segments for r in facts.replies])
    outcome = interaction_outcome(
        occurrences,
        end_reason=end_reason,
        handoff_count=len(facts.handoffs),
        any_abstain_route=any(r.route == "abstain" for r in facts.replies),
    )

    first = facts.handoffs[0] if facts.handoffs else None
    time_to_claim = (
        int((first.claimed_at - first.created_at).total_seconds())
        if first is not None and first.claimed_at is not None
        else None
    )

    # D10 / REQ-R3: the sentiment call is excluded from every interaction cost.
    costs = {s: c for s, c in facts.step_costs.items() if s != _SENTIMENT_STEP}

    def step_cost(step: str) -> Decimal:
        return costs[step].cost_usd if step in costs else Decimal(0)

    row = InteractionRow(
        conversation_id=facts.conversation_id,
        source="real",
        started_at=started_at,
        ended_at=ended_at,
        end_reason=end_reason,
        duration_s=int((ended_at - started_at).total_seconds()),
        language=facts.language,
        # D11: the label mapped like the staff list; the customer id never gets here.
        country=COUNTRY_LABELS.get(facts.country_label) if facts.country_label else None,
        channel=facts.channel,
        customer_messages=roles.count("customer"),
        bot_messages=roles.count("bot"),
        agent_messages=roles.count("agent"),
        turns=len({m.turn_id for m in facts.messages if m.turn_id is not None}),
        real_intent_count=outcome.real_intent_count,
        resolved=outcome.resolved,
        abandoned=outcome.abandoned,
        abstained=outcome.abstained,
        degraded=any(r.degraded for r in facts.replies),
        escalated=bool(facts.handoffs),
        handoff_count=len(facts.handoffs),
        handoff_queue=first.queue if first is not None else None,
        handoff_reason=first.reason if first is not None else None,
        handoff_cause_group=(cause_group(first.reason) if first is not None else None),
        time_to_claim_s=time_to_claim,
        cost_usd=sum((c.cost_usd for c in costs.values()), Decimal(0)),
        cost_nlu_usd=step_cost("nlu"),
        cost_compose_usd=step_cost("compose"),
        cost_handoff_summary_usd=step_cost("handoff_summary"),
        llm_call_count=sum(c.calls for c in costs.values()),
        computed_at=now,
        metrics_version=METRICS_VERSION,
    )
    return row, occurrences


async def _compute_and_store(
    store: AnalyticsStore, conversation_id: str, *, now: datetime, settings: Settings
) -> bool:
    facts = await store.load_facts(conversation_id)
    if facts is None:
        return False
    computed = compute_interaction(facts, now=now, idle_minutes=settings.analytics_idle_minutes)
    if computed is None:  # unfinished: no row (R3)
        return False
    await store.upsert_interaction(*computed)
    return True


# --- mock seeding ----------------------------------------------------------------


async def _seed_mock(
    store: AnalyticsStore, state: WorkerState, *, now: datetime, s: Settings
) -> int:
    """Seed each missing local day, oldest first; returns how many days were generated."""
    tz = ZoneInfo(s.analytics_timezone)
    today = now.astimezone(tz).date()
    first = today - timedelta(days=s.analytics_mock_backfill_days - 1)
    start = first
    if state.mock_seeded_through is not None:
        start = max(first, state.mock_seeded_through + timedelta(days=1))
    profile = load_profile()
    days = 0
    day = start
    while day <= today:
        # Per-day insert + marker: a crash resumes at the first unseeded day.
        await store.insert_mock(generate_day(day, profile, tz))
        await store.set_mock_seeded_through(day)
        days += 1
        day += timedelta(days=1)
    return days


# --- sentiment -------------------------------------------------------------------


async def _score_targets(
    store: AnalyticsStore,
    scorer: SentimentScorer,
    targets: Sequence[ScoringTarget],
    *,
    now: datetime,
) -> tuple[int, bool]:
    """Score one conversation at a time. Returns (scored, unavailable).

    A `None` result stops scoring for the rest of the run (R11: no hammering a
    provider that just failed its retries); the rows stay null for a later pass.
    """
    scored = 0
    for target in targets:
        messages = await store.customer_messages(target.conversation_id)
        if not messages:
            continue
        result = await scorer.score(target.conversation_id, messages, target.language or "es")
        if result is None:
            return scored, True
        await store.set_sentiment(target.conversation_id, result, now)
        scored += 1
    return scored, False


# --- entry points ----------------------------------------------------------------


async def run_pass(
    store: AnalyticsStore, scorer: SentimentScorer, *, now: datetime, settings: Settings
) -> PassStats:
    """One pass: compute finished candidates, advance the watermark, seed mock, score.

    A conversation whose compute raises is skipped and logged
    (`analytics.compute_failed`); the rest of the pass goes on. The watermark does
    not advance while any conversation fails, so it is retried next pass. A
    permanently failing conversation therefore freezes the watermark (accepted);
    it shows up as repeated `analytics.compute_failed` logs.
    """
    state = await store.get_state()
    # Minus the idle window, so a conversation that was unfinished last pass is seen
    # again once it has been quiet long enough (D7).
    since = (
        None
        if state.watermark is None
        else state.watermark - timedelta(minutes=settings.analytics_idle_minutes)
    )
    written = 0
    failed = 0
    for conversation_id in await store.list_candidates(since):
        try:
            if await _compute_and_store(store, conversation_id, now=now, settings=settings):
                written += 1
        except Exception as exc:  # one bad conversation must not stall the others
            failed += 1
            _logger.error(
                "analytics.compute_failed",
                conversation_id=conversation_id,
                exc_type=type(exc).__name__,
            )
    # A failure holds the watermark where it was, so the next pass sees the
    # failed conversation again (upserts are idempotent, D9). The protocol returns
    # ids only, so "stop at the failed conversation" is "do not advance".
    if not failed:
        await store.set_watermark(now)

    mock_days = 0
    if settings.analytics_mock_enabled:
        mock_days = await _seed_mock(store, state, now=now, s=settings)

    targets = await store.list_scoring_targets(all_real=False, limit=_SCORE_BATCH)
    scored, unavailable = await _score_targets(store, scorer, targets, now=now)
    return PassStats(written, mock_days, scored, unavailable)


async def run_recompute(store: AnalyticsStore, *, now: datetime, settings: Settings) -> int:
    """Recompute real rows with an older `metrics_version`; sentiment columns are kept."""
    done = 0
    for conversation_id in await store.list_stale(METRICS_VERSION):
        if await _compute_and_store(store, conversation_id, now=now, settings=settings):
            done += 1
    return done


async def run_rescore_sentiment(
    store: AnalyticsStore, scorer: SentimentScorer, *, now: datetime
) -> PassStats:
    """Re-score every real row (after a model or prompt switch)."""
    targets = await store.list_scoring_targets(all_real=True, limit=None)
    scored, unavailable = await _score_targets(store, scorer, targets, now=now)
    return PassStats(scored=scored, sentiment_unavailable=unavailable)


# --- CLI -------------------------------------------------------------------------


def validate_database_url(raw: str) -> URL:
    """The worker's URL, or a start-up error. Messages never include the URL."""
    if not raw.strip():
        raise WorkerConfigError("ANALYTICS_DATABASE_URL is empty")
    try:
        url = make_url(raw)
    except ArgumentError:
        raise WorkerConfigError("ANALYTICS_DATABASE_URL is not a valid database URL") from None
    # Compose interpolates an empty ANALYTICS_DB_PASSWORD into a non-empty URL, so
    # emptiness has to be checked on the parsed password (human decision, T10).
    if not url.password:
        raise WorkerConfigError("ANALYTICS_DATABASE_URL has no password")
    if (url.database or "").startswith(_EVAL_DB_PREFIX):
        raise WorkerConfigError("the analytics worker never runs on an eval database")
    return url


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m app.domains.analytics.worker",
        description="Interaction analytics worker. No flag: loop every "
        "ANALYTICS_WORKER_INTERVAL_S seconds.",
    )
    parser.add_argument("--once", action="store_true", help="run one pass and exit")
    parser.add_argument(
        "--recompute",
        action="store_true",
        help="recompute real rows with an older metrics_version (keeps sentiment), then exit",
    )
    parser.add_argument(
        "--rescore-sentiment",
        action="store_true",
        help="re-score sentiment of every real row, then exit",
    )
    return parser.parse_args(argv)


async def _amain(args: argparse.Namespace, settings: Settings, url: URL) -> None:
    # Imported here so `--help` and the tests need no database driver wiring, and
    # the module stays free of a hard dependency on the Postgres store.
    repository = importlib.import_module("app.domains.analytics.repository")
    engine = repository.build_engine(url.render_as_string(hide_password=False))
    store: AnalyticsStore = repository.PostgresAnalyticsStore(engine)
    scorer = HaikuSentimentScorer(_LedgerSink(store))
    try:
        if args.recompute or args.rescore_sentiment:
            if args.recompute:
                recomputed = await run_recompute(store, now=datetime.now(UTC), settings=settings)
                _logger.info("analytics.recompute", recomputed=recomputed)
            if args.rescore_sentiment:
                stats = await run_rescore_sentiment(store, scorer, now=datetime.now(UTC))
                _logger.info(
                    "analytics.rescore",
                    scored=stats.scored,
                    unavailable=stats.sentiment_unavailable,
                )
            return
        if args.once:
            stats = await run_pass(store, scorer, now=datetime.now(UTC), settings=settings)
            _log_pass(stats)
            return
        while True:
            try:
                stats = await run_pass(store, scorer, now=datetime.now(UTC), settings=settings)
                _log_pass(stats)
            except Exception as exc:  # a bad pass must not kill the loop (fields only)
                _logger.error("analytics.pass_failed", exc_type=type(exc).__name__)
            await asyncio.sleep(settings.analytics_worker_interval_s)
    finally:
        await engine.dispose()


def _log_pass(stats: PassStats) -> None:
    _logger.info(
        "analytics.pass",
        written=stats.written,
        mock_days=stats.mock_days,
        scored=stats.scored,
        sentiment_unavailable=stats.sentiment_unavailable,
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    configure_logging()
    setup_log_export("analytics-worker")
    settings = get_settings()
    try:
        url = validate_database_url(settings.analytics_database_url)
    except WorkerConfigError as exc:
        print(f"analytics worker: {exc}", file=sys.stderr)
        return 2
    asyncio.run(_amain(args, settings, url))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
