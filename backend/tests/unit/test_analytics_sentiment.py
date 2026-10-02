"""Worker sentiment rules: masked text only, and graceful unavailability.

No database and no network: an in-memory `AnalyticsStore` and a stub chat model
behind the real `StructuredLLMClient` (same seam as `test_llm_client.py`).
`asyncio.run` drives the async code since the project has no async test runner.
"""

import asyncio
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
import structlog
from anthropic import APIConnectionError

from app.core.config import Settings, get_settings
from app.core.llm import LLMCallRecord, LLMCallSink, LLMClient
from app.core.llm import client as llm_client
from app.core.llm.client import StructuredLLMClient
from app.core.llm.settings import LLMSettings
from app.domains.analytics.mock import MockInteraction
from app.domains.analytics.sentiment import HaikuSentimentScorer, SentimentLabels, SentimentResult
from app.domains.analytics.service import Occurrence
from app.domains.analytics.worker import (
    ConversationFacts,
    InteractionRow,
    MessageFact,
    ReplyFact,
    ScoringTarget,
    StepCost,
    WorkerState,
    _LedgerSink,
    run_pass,
)

NOW = datetime(2026, 10, 2, 15, 0, tzinfo=UTC)
CONV = "11111111-1111-1111-1111-111111111111"
RAW_EMAIL = "ana.perez@example.com"  # lives only in the fake's vault, like the real PII vault


@dataclass
class FakeStore:
    """In-memory `AnalyticsStore`: the vault holds raw text; only masked text is exposed."""

    vault: dict[str, str] = field(default_factory=lambda: {"⟨EMAIL_1⟩": RAW_EMAIL})
    rows: dict[str, InteractionRow] = field(default_factory=dict)
    sentiment: dict[str, SentimentResult] = field(default_factory=dict)
    ledger: list[LLMCallRecord] = field(default_factory=list)
    watermark: datetime | None = None

    def _facts(self) -> ConversationFacts:
        t0 = NOW - timedelta(hours=2)
        msgs = [
            MessageFact("customer", "t1", t0, "Hola, soy ⟨EMAIL_1⟩ y quiero bloquear mi tarjeta"),
            MessageFact("bot", "t1", t0 + timedelta(seconds=5), "Listo, ¿confirmas?"),
            MessageFact("customer", "t2", t0 + timedelta(seconds=30), "sí, gracias"),
        ]
        return ConversationFacts(
            conversation_id=CONV,
            status="closed",
            language="es",
            channel="web",
            country_label="Colombia",
            messages=msgs,
            replies=[ReplyFact("card_block", False, [])],
            handoffs=[],
            # The sentiment row is in the ledger already (a rescore case): it must not count.
            step_costs={
                "nlu": StepCost(Decimal("0.017"), 1),
                "compose": StepCost(Decimal("0.005"), 1),
                "sentiment": StepCost(Decimal("0.9"), 1),
            },
        )

    async def get_state(self) -> WorkerState:
        return WorkerState(self.watermark, None)

    async def set_watermark(self, watermark: datetime) -> None:
        self.watermark = watermark

    async def set_mock_seeded_through(self, day: date) -> None:
        raise AssertionError("mock is off in these tests")

    async def list_candidates(self, since: datetime | None) -> list[str]:
        return [CONV]

    async def load_facts(self, conversation_id: str) -> ConversationFacts | None:
        return self._facts()

    async def upsert_interaction(self, row: InteractionRow, intents: Sequence[Occurrence]) -> None:
        self.rows[row.conversation_id] = row

    async def insert_mock(self, rows: Sequence[MockInteraction]) -> None:
        raise AssertionError("mock is off in these tests")

    async def list_scoring_targets(
        self, *, all_real: bool, limit: int | None
    ) -> list[ScoringTarget]:
        return [
            ScoringTarget(cid, r.language)
            for cid, r in self.rows.items()
            if all_real or cid not in self.sentiment
        ]

    async def customer_messages(self, conversation_id: str) -> list[str]:
        return [m.content_masked or "" for m in self._facts().messages if m.role == "customer"]

    async def set_sentiment(
        self, conversation_id: str, result: SentimentResult, scored_at: datetime
    ) -> None:
        self.sentiment[conversation_id] = result

    async def list_stale(self, metrics_version: int) -> list[str]:
        return []

    async def record_llm_call(self, call: LLMCallRecord) -> None:
        self.ledger.append(call)


class _Runnable:
    def __init__(self, outputs: list[Any]) -> None:
        self._outputs = outputs
        self.requests: list[Any] = []

    async def ainvoke(self, messages: Any) -> Any:
        self.requests.append(messages)
        out = self._outputs.pop(0)
        if isinstance(out, BaseException):
            raise out
        return out


class _ChatModel:
    def __init__(self, outputs: list[Any]) -> None:
        self.runnable = _Runnable(outputs)

    def with_structured_output(self, schema: Any, **_: Any) -> _Runnable:
        return self.runnable


async def _no_sleep(_: float) -> None:
    return None


def _good_output() -> dict[str, Any]:
    raw = SimpleNamespace(usage_metadata={"input_tokens": 1000, "output_tokens": 200})
    labels = SentimentLabels(overall="positive", start="neutral", end="positive")
    return {"raw": raw, "parsed": labels, "parsing_error": None}


def _scorer(store: FakeStore, chat: _ChatModel) -> HaikuSentimentScorer:
    def factory(sink: LLMCallSink) -> LLMClient:
        return StructuredLLMClient(
            LLMSettings(_env_file=None),
            chat_model_factory=lambda s, step: chat,
            sink=sink,
            sleep=_no_sleep,
        )

    return HaikuSentimentScorer(_LedgerSink(store), client_factory=factory)


def _settings() -> Settings:
    return Settings(_env_file=None, analytics_mock_enabled=False, analytics_idle_minutes=30)


@pytest.fixture
def llm_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[pytest.MonkeyPatch]:
    monkeypatch.setenv("LLM_DISABLED", "false")
    get_settings.cache_clear()
    # A cached module logger would swallow later `capture_logs()` in test_llm_client.
    monkeypatch.setattr(llm_client, "_logger", structlog.get_logger())
    yield monkeypatch
    get_settings.cache_clear()


def test_sentiment_masked_only(llm_env: pytest.MonkeyPatch) -> None:
    """R5: the request holds the token, never the raw value; the call's cost stays apart."""
    store = FakeStore()
    chat = _ChatModel([_good_output()])

    stats = asyncio.run(run_pass(store, _scorer(store, chat), now=NOW, settings=_settings()))

    assert stats.scored == 1
    sent = str(chat.runnable.requests)
    assert RAW_EMAIL not in sent
    assert "⟨EMAIL_1⟩" in sent
    result = store.sentiment[CONV]
    assert (result.overall, result.start, result.end) == ("positive", "neutral", "positive")
    # 1000 in / 200 out on Haiku 4.5: $0.002, recorded on the sentiment column only.
    assert result.cost_usd == Decimal("0.002")
    row = store.rows[CONV]
    assert row.cost_usd == Decimal("0.022")  # nlu + compose; the sentiment step is left out
    assert row.llm_call_count == 2
    assert row.country == "CO"
    assert [r.step for r in store.ledger] == ["sentiment"]  # ledgered through the store


def test_sentiment_unavailable(llm_env: pytest.MonkeyPatch) -> None:
    """R11, D13: no call under LLM_DISABLED; at most retry_max + 1 attempts otherwise; row kept."""
    # 1. LLM_DISABLED: no call at all.
    llm_env.setenv("LLM_DISABLED", "true")
    get_settings.cache_clear()
    store = FakeStore()
    chat = _ChatModel([])
    stats = asyncio.run(run_pass(store, _scorer(store, chat), now=NOW, settings=_settings()))
    assert stats.sentiment_unavailable
    assert chat.runnable.requests == []
    assert CONV in store.rows
    assert CONV not in store.sentiment

    # 2. A model that always fails: bounded attempts, the row is still written.
    llm_env.setenv("LLM_DISABLED", "false")
    get_settings.cache_clear()
    retry_max = get_settings().retry_max
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    failure = APIConnectionError(message="down", request=request)
    store = FakeStore()
    chat = _ChatModel([failure] * (retry_max + 5))
    stats = asyncio.run(run_pass(store, _scorer(store, chat), now=NOW, settings=_settings()))
    assert stats.sentiment_unavailable
    assert len(chat.runnable.requests) <= retry_max + 1
    assert CONV in store.rows and CONV not in store.sentiment

    # 3. A later pass retries the null row (D13).
    chat_ok = _ChatModel([_good_output()])
    stats = asyncio.run(run_pass(store, _scorer(store, chat_ok), now=NOW, settings=_settings()))
    assert stats.scored == 1 and CONV in store.sentiment
