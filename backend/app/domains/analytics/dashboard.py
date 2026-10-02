"""Read side of the analytics dashboard: one summary over the fact tables.

Spec `interaction-analytics-dashboard.md` D1, D3, D4, D10-D12 and "Contracts".
The module reads only `analytics.interactions` and `analytics.interaction_intents`
(ADR-033: the dashboard reads only this schema) through the app's shared engine,
inside one read-only snapshot, so every block describes the same rows.

Every block applies the same row filter (`_where`): finished rows only
(`ended_at <= now()`), the inclusive local-date range, and the optional
language, country and source filters. Money leaves as `float` USD; formatting
is the frontend's job (R4).
"""

from datetime import date, datetime, timedelta
from typing import Any, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.config import get_settings
from app.core.db import get_engine

__all__ = [
    "AnalyticsSummary",
    "AnalyticsTimeout",
    "AppliedFilters",
    "InvalidDateRange",
    "get_summary",
    "resolve_filters",
]

MAX_RANGE_DAYS = 92
DEFAULT_RANGE_DAYS = 7
RECENT_LIMIT = 50
_STATEMENT_TIMEOUT_SQLSTATE = "57014"

Language = Literal["es", "pt"]
Country = Literal["MX", "CO", "AR"]
Source = Literal["all", "real", "mock"]
Bucket = Literal["escalated", "resolved", "abandoned", "abstained", "other"]


class InvalidDateRange(ValueError):
    """`date_from` is after `date_to`, or the range is longer than 92 days (D10)."""


class AnalyticsTimeout(Exception):
    """The summary transaction hit its 5 s statement timeout (D10)."""


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


class AppliedFilters(_Frozen):
    date_from: date
    date_to: date
    language: Language | None
    country: Country | None
    source: Source
    timezone: str


class Rate(_Frozen):
    rate: float | None
    num: int
    den: int


class CostPerInteraction(_Frozen):
    avg_usd: float | None
    total_usd: float
    count: int


class MessagesPerInteraction(_Frozen):
    avg: float | None
    count: int


class Tiles(_Frozen):
    interactions: int
    resolution: Rate
    escalation: Rate
    cost_per_interaction: CostPerInteraction
    messages_per_interaction: MessagesPerInteraction
    negative_sentiment: Rate


class PerDay(_Frozen):
    day: date
    escalated: int
    resolved: int
    abandoned: int
    abstained: int
    other: int


class IntentRow(_Frozen):
    intent: str
    count: int
    resolution: Rate


class CauseGroupCount(_Frozen):
    group: str | None
    count: int


class QueueCount(_Frozen):
    queue: str | None
    count: int


class Escalations(_Frozen):
    by_cause_group: list[CauseGroupCount]
    by_queue: list[QueueCount]
    time_to_claim_median_s: float | None
    time_to_claim_count: int


class SentimentOverall(_Frozen):
    negative: int
    neutral: int
    positive: int
    scored: int


class SentimentTrajectory(_Frozen):
    better: int
    same: int
    worse: int
    scored: int


class SentimentBlock(_Frozen):
    overall: SentimentOverall
    trajectory: SentimentTrajectory


class CostDay(_Frozen):
    day: date
    nlu_usd: float
    compose_usd: float
    handoff_summary_usd: float


class PerResolved(_Frozen):
    usd: float | None
    resolved: int


class CostBlock(_Frozen):
    per_day: list[CostDay]
    total_usd: float
    per_resolved: PerResolved
    sentiment_overhead_usd: float


class RecentInteraction(_Frozen):
    conversation_id: UUID
    source: Literal["real", "mock"]
    ended_at: datetime
    end_reason: str
    intents: list[str]
    outcome: Bucket
    sentiment_overall: str | None
    cost_usd: float


class AnalyticsSummary(_Frozen):
    filters: AppliedFilters
    includes_mock: bool
    tiles: Tiles
    per_day: list[PerDay]
    intents: list[IntentRow]
    escalations: Escalations
    sentiment: SentimentBlock
    cost: CostBlock
    recent: list[RecentInteraction]


def resolve_filters(
    date_from: date | None,
    date_to: date | None,
    language: Language | None,
    country: Country | None,
    source: Source,
) -> AppliedFilters:
    """Fill the defaults (7 days ending today, local) and check the range (D10)."""
    tz_name = get_settings().analytics_timezone
    if date_to is None:
        date_to = datetime.now(ZoneInfo(tz_name)).date()
    if date_from is None:
        date_from = date_to - timedelta(days=DEFAULT_RANGE_DAYS - 1)
    if date_from > date_to:
        raise InvalidDateRange("date_from is after date_to")
    if (date_to - date_from).days + 1 > MAX_RANGE_DAYS:
        raise InvalidDateRange(f"the range is longer than {MAX_RANGE_DAYS} days")
    return AppliedFilters(
        date_from=date_from,
        date_to=date_to,
        language=language,
        country=country,
        source=source,
        timezone=tz_name,
    )


# D1: exclusive buckets, taken in this order. Also the "outcome" of a recent row.
_BUCKET_SQL = """CASE
    WHEN i.escalated THEN 'escalated'
    WHEN i.resolved IS TRUE THEN 'resolved'
    WHEN i.abandoned THEN 'abandoned'
    WHEN i.abstained THEN 'abstained'
    ELSE 'other' END"""

# D3: a bot-offered intent the customer declined is not a customer need.
_COUNTED_INTENT_SQL = "NOT (n.bot_offered AND n.outcome = 'cancelled')"

_RANK = "CASE {c} WHEN 'negative' THEN 0 WHEN 'neutral' THEN 1 WHEN 'positive' THEN 2 END"
_START_RANK = _RANK.format(c="i.sentiment_start")
_END_RANK = _RANK.format(c="i.sentiment_end")

_TILES_SQL = f"""
SELECT
    count(*) AS n,
    count(*) FILTER (WHERE i.resolved IS TRUE) AS resolved_n,
    count(*) FILTER (WHERE i.resolved IS NOT NULL) AS resolved_den,
    count(*) FILTER (WHERE i.escalated) AS escalated_n,
    COALESCE(sum(i.cost_usd), 0) AS cost_total,
    COALESCE(sum(i.customer_messages + i.bot_messages + i.agent_messages), 0) AS messages,
    count(*) FILTER (WHERE i.sentiment_overall = 'negative') AS s_negative,
    count(*) FILTER (WHERE i.sentiment_overall = 'neutral') AS s_neutral,
    count(*) FILTER (WHERE i.sentiment_overall = 'positive') AS s_positive,
    count(i.sentiment_overall) AS s_scored,
    count(*) FILTER (WHERE {_END_RANK} > {_START_RANK}) AS t_better,
    count(*) FILTER (WHERE {_END_RANK} = {_START_RANK}) AS t_same,
    count(*) FILTER (WHERE {_END_RANK} < {_START_RANK}) AS t_worse,
    count(*) FILTER (WHERE i.sentiment_start IS NOT NULL
                       AND i.sentiment_end IS NOT NULL) AS t_scored,
    COALESCE(sum(i.sentiment_cost_usd), 0) AS sentiment_cost,
    COALESCE(bool_or(i.source = 'mock'), false) AS includes_mock,
    percentile_cont(0.5) WITHIN GROUP (ORDER BY i.time_to_claim_s) AS claim_median,
    count(i.time_to_claim_s) AS claim_count
FROM analytics.interactions i
WHERE {{where}}
"""

_PER_DAY_SQL = f"""
SELECT CAST((i.ended_at AT TIME ZONE :tz) AS date) AS day, {_BUCKET_SQL} AS bucket,
       count(*) AS n
FROM analytics.interactions i
WHERE {{where}}
GROUP BY 1, 2
"""

_COST_DAY_SQL = """
SELECT CAST((i.ended_at AT TIME ZONE :tz) AS date) AS day,
       sum(i.cost_nlu_usd) AS nlu, sum(i.cost_compose_usd) AS compose,
       sum(i.cost_handoff_summary_usd) AS handoff_summary
FROM analytics.interactions i
WHERE {where}
GROUP BY 1
"""

_INTENTS_SQL = f"""
SELECT n.intent, count(*) AS n, count(*) FILTER (WHERE n.outcome = 'resolved') AS resolved_n
FROM analytics.interactions i
JOIN analytics.interaction_intents n ON n.conversation_id = i.conversation_id
WHERE {{where}} AND {_COUNTED_INTENT_SQL}
GROUP BY n.intent
ORDER BY n DESC, n.intent
"""

# The first handoff's cause group and queue, as card 1 stored them.
_CAUSE_SQL = """
SELECT i.handoff_cause_group AS value, count(*) AS n
FROM analytics.interactions i
WHERE {where} AND i.escalated
GROUP BY 1
ORDER BY n DESC, value NULLS LAST
"""
_QUEUE_SQL = _CAUSE_SQL.replace("handoff_cause_group", "handoff_queue")

_RECENT_SQL = f"""
SELECT i.conversation_id, i.source, i.ended_at, i.end_reason, {_BUCKET_SQL} AS outcome,
       i.sentiment_overall, i.cost_usd,
       COALESCE((
           SELECT array_agg(n.intent ORDER BY n.seq)
           FROM analytics.interaction_intents n
           WHERE n.conversation_id = i.conversation_id AND {_COUNTED_INTENT_SQL}
       ), ARRAY[]::text[]) AS intents
FROM analytics.interactions i
WHERE {{where}}
ORDER BY i.ended_at DESC, i.conversation_id
LIMIT {RECENT_LIMIT}
"""


def _where(filters: AppliedFilters) -> tuple[str, dict[str, Any]]:
    """The row filter every block shares, with its bind parameters."""
    clauses = [
        "i.ended_at <= now()",
        "CAST((i.ended_at AT TIME ZONE :tz) AS date) BETWEEN :date_from AND :date_to",
    ]
    params: dict[str, Any] = {
        "tz": filters.timezone,
        "date_from": filters.date_from,
        "date_to": filters.date_to,
    }
    for column, value in (
        ("language", filters.language),
        ("country", filters.country),
    ):
        if value is not None:
            clauses.append(f"i.{column} = :{column}")
            params[column] = value
    if filters.source != "all":
        clauses.append("i.source = :source")
        params["source"] = filters.source
    return " AND ".join(clauses), params


def _rate(num: int, den: int) -> Rate:
    return Rate(rate=num / den if den else None, num=num, den=den)


def _days(filters: AppliedFilters) -> list[date]:
    span = (filters.date_to - filters.date_from).days
    return [filters.date_from + timedelta(days=k) for k in range(span + 1)]


def _is_timeout(exc: DBAPIError) -> bool:
    orig: BaseException | None = exc.orig
    while orig is not None:
        code = getattr(orig, "sqlstate", None) or getattr(orig, "pgcode", None)
        if code == _STATEMENT_TIMEOUT_SQLSTATE:
            return True
        orig = orig.__cause__
    return False


async def get_summary(filters: AppliedFilters) -> AnalyticsSummary:
    """Every dashboard block for `filters`, from one read-only snapshot (D10)."""
    where, params = _where(filters)
    try:
        async with get_engine().connect() as conn:
            # First statements of the transaction: a stable snapshot, then the cap.
            await conn.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
            await conn.execute(text("SET LOCAL statement_timeout = '5s'"))

            async def rows(sql: str) -> list[Any]:
                return list((await conn.execute(text(sql.format(where=where)), params)).all())

            tiles = (await rows(_TILES_SQL))[0]
            day_rows = await rows(_PER_DAY_SQL)
            cost_rows = await rows(_COST_DAY_SQL)
            intent_rows = await rows(_INTENTS_SQL)
            cause_rows = await rows(_CAUSE_SQL)
            queue_rows = await rows(_QUEUE_SQL)
            recent_rows = await rows(_RECENT_SQL)
    except DBAPIError as exc:
        if _is_timeout(exc):
            raise AnalyticsTimeout from exc
        raise

    return _assemble(
        filters, tiles, day_rows, cost_rows, intent_rows, cause_rows, queue_rows, recent_rows
    )


def _assemble(
    filters: AppliedFilters,
    t: Any,
    day_rows: list[Any],
    cost_rows: list[Any],
    intent_rows: list[Any],
    cause_rows: list[Any],
    queue_rows: list[Any],
    recent_rows: list[Any],
) -> AnalyticsSummary:
    n = t.n
    cost_total = float(t.cost_total)
    by_day: dict[date, dict[str, int]] = {d: {} for d in _days(filters)}
    for r in day_rows:
        by_day[r.day][r.bucket] = r.n
    costs = {r.day: r for r in cost_rows}
    zero = {"nlu": 0, "compose": 0, "handoff_summary": 0}
    cost_days = []
    for d in by_day:
        c = costs.get(d)
        cost_days.append(
            CostDay(
                day=d,
                nlu_usd=float(c.nlu if c else zero["nlu"]),
                compose_usd=float(c.compose if c else zero["compose"]),
                handoff_summary_usd=float(c.handoff_summary if c else zero["handoff_summary"]),
            )
        )
    return AnalyticsSummary(
        filters=filters,
        includes_mock=t.includes_mock,
        tiles=Tiles(
            interactions=n,
            resolution=_rate(t.resolved_n, t.resolved_den),
            escalation=_rate(t.escalated_n, n),
            cost_per_interaction=CostPerInteraction(
                avg_usd=cost_total / n if n else None, total_usd=cost_total, count=n
            ),
            messages_per_interaction=MessagesPerInteraction(
                avg=t.messages / n if n else None, count=n
            ),
            negative_sentiment=_rate(t.s_negative, t.s_scored),
        ),
        per_day=[
            PerDay(
                day=d,
                escalated=b.get("escalated", 0),
                resolved=b.get("resolved", 0),
                abandoned=b.get("abandoned", 0),
                abstained=b.get("abstained", 0),
                other=b.get("other", 0),
            )
            for d, b in by_day.items()
        ],
        intents=[
            IntentRow(intent=r.intent, count=r.n, resolution=_rate(r.resolved_n, r.n))
            for r in intent_rows
        ],
        escalations=Escalations(
            by_cause_group=[CauseGroupCount(group=r.value, count=r.n) for r in cause_rows],
            by_queue=[QueueCount(queue=r.value, count=r.n) for r in queue_rows],
            time_to_claim_median_s=(float(t.claim_median) if t.claim_median is not None else None),
            time_to_claim_count=t.claim_count,
        ),
        sentiment=SentimentBlock(
            overall=SentimentOverall(
                negative=t.s_negative,
                neutral=t.s_neutral,
                positive=t.s_positive,
                scored=t.s_scored,
            ),
            trajectory=SentimentTrajectory(
                better=t.t_better, same=t.t_same, worse=t.t_worse, scored=t.t_scored
            ),
        ),
        cost=CostBlock(
            per_day=cost_days,
            total_usd=cost_total,
            per_resolved=PerResolved(
                usd=cost_total / t.resolved_n if t.resolved_n else None, resolved=t.resolved_n
            ),
            sentiment_overhead_usd=float(t.sentiment_cost),
        ),
        recent=[
            RecentInteraction(
                conversation_id=r.conversation_id,
                source=r.source,
                ended_at=r.ended_at,
                end_reason=r.end_reason,
                intents=list(r.intents),
                outcome=r.outcome,
                sentiment_overall=r.sentiment_overall,
                cost_usd=float(r.cost_usd),
            )
            for r in recent_rows
        ],
    )
