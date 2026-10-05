"""`FakeBank`: `BankReadTools` over the raw CSVs via DuckDB.

See `docs/specs/d1-b-agent-sandbox.md` §"Decisions" D1, D17. The sandbox
points this at `data/`; tests point it at the invented
`backend/tests/fixtures/fakebank/` fixture. Either way the schema is the raw,
unshifted one described in the plan's "Facts checked against the repo": UTF-8
with BOM, `all_varchar=true` so every numeric/date column is cast in SQL
rather than trusted to DuckDB's sniffer.

R1: a `FakeBank` is bound to one `ToolContext` at construction and every
query filters on `ctx.customer_id` directly (a bound DuckDB parameter, never
string-formatted into SQL; only the non-customer-controlled file paths are).
For a single card lookup by id, that means the details query itself is
`WHERE product_id = ? AND customer_id = ?`: it can only ever return the
caller's own card. Only when it returns nothing does a second, narrower query
run to tell an unknown id (`NotFound`) apart from one that belongs to another
customer (`AccessDenied`) -- that probe selects a single column
(`product_type`, to confirm it is a card and not some other product) and
never a balance, limit, card number or other customer's data.

D7: `FakeBankOverlay` is the per-session, in-memory record of what this
sandbox conversation has done -- locked, blocked and replaced cards -- since
neither Postgres nor `app.card_controls` exist yet. `FakeBank` reads apply it
(`list_cards`/`get_card_details` show `locked` and an overlay-blocked card as
`Blocked`); `FakeBankWrites` (`BankWriteTools`, D2-K) mutates it and then
re-reads it before returning `verified=True` (R3). `make_fakebank_factory`
returns one read factory and one write factory sharing a single overlay, so
a session's writes are visible to its own reads.

D11: `FakeBankOverlay.results` maps a caller-supplied `idempotency_key` to the
`ActionResult` it produced. Each `FakeBankWrites` write checks that map first:
a replayed key returns the stored result untouched (nothing mutated, nothing
re-read); a new key runs the write as before and stores the result under it.
"""

import asyncio
import secrets
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal
from uuid import UUID, uuid4

import duckdb

from app.core.actions import ActionResult
from app.core.errors import AccessDenied, NotFound, ToolUnavailable
from app.core.pii import KnownPii
from app.domains.cards.schemas import (
    AddressRef,
    BlockOrigin,
    BlockReason,
    CardDetails,
    CardSummary,
    CustomerCardRequest,
)
from app.domains.conversation.tools.bank import BankReadTools, BankToolsFactory
from app.domains.conversation.tools.context import ToolContext
from app.domains.conversation.tools.write import (
    BankWriteTools,
    BankWriteToolsFactory,
    PendingCardRequests,
)
from app.domains.customers.schemas import CustomerProfile
from app.domains.disputes.schemas import PrioritySignals
from app.domains.localization.schemas import FxRate
from app.domains.policy.decline_codes import lookup_decline_code
from app.domains.policy.disputes import load_disputes_policy
from app.domains.safety.vault import InMemoryPiiVault
from app.domains.transactions.schemas import DeclineExplanation, TxFilter, TxView

__all__ = ["FakeBank", "FakeBankOverlay", "FakeBankWrites", "make_fakebank_factory"]


@dataclass
class FakeBankOverlay:
    """What this sandbox session has done to its own cards (D7).

    Plain per-session state, not persisted: a fresh session (a fresh
    `make_fakebank_factory` call) starts with all three empty. `locked` and
    `blocked` hold card ids; `replacements` maps a card id to the
    `tracking_id` its last `order_replacement` returned.
    """

    locked: set[str] = field(default_factory=set)
    blocked: set[str] = field(default_factory=set)
    replacements: dict[str, str] = field(default_factory=dict)
    results: dict[str, ActionResult] = field(default_factory=dict)
    claim_priorities: dict[str, Literal["High"] | None] = field(default_factory=dict)
    """Each `create_claim` case id's priority (SA1): `"High"` when that call's
    `priority_flags` was non-empty, `None` otherwise. The fake dataset has no
    `bank.complaints` row to write it into."""
    vault: InMemoryPiiVault = field(default_factory=InMemoryPiiVault)
    """Where a test stages profile-form values (`stage_form_values`); `request_card`
    reads them back from here, as the Postgres path reads `PostgresPiiVault`."""
    card_requests: dict[UUID, dict[str, Any]] = field(default_factory=dict)
    """Each request by id: `{reference, kind, card_kind, status, changed_fields,
    product_id, reason_code, created_at}` (`status` is `"pending"` here)."""
    profile: dict[str, str] = field(default_factory=dict)
    """Profile values written by `request_card`, over the fixture's."""
    profile_history: list[dict[str, Any]] = field(default_factory=list)
    """One `{field, old, new, actor, at}` entry per field a request changed."""


_COUNTRY_LABELS: dict[str, Literal["MX", "CO", "AR"]] = {
    "México": "MX",
    "Colombia": "CO",
    "Argentina": "AR",
}
_CARD_KINDS: dict[str, Literal["credit", "debit"]] = {
    "Tarjeta Crédito": "credit",
    "Tarjeta Débito": "debit",
}


def _sql_literal(path: Path) -> str:
    """Quote `path` as a SQL string literal.

    Only ever called with fixture/data-directory paths chosen by code (never
    `customer_id` or other tool input): the injection surface DuckDB
    parameters close is customer-supplied values, not this constant path.
    """
    return "'" + str(path).replace("\\", "/").replace("'", "''") + "'"


def _run_query(sql: str, params: list[Any]) -> list[dict[str, Any]]:
    """Run one parameterized query against a fresh in-memory DuckDB connection.

    A fresh connection per call keeps `FakeBank` stateless; there is no
    server process here to make pooling worthwhile.
    """
    con = duckdb.connect(":memory:")
    try:
        cursor = con.execute(sql, params)
        columns = [column[0] for column in cursor.description]
        return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]
    finally:
        con.close()


def _known_pii(
    document_number: str | None, first_name: str | None, last_name: str | None
) -> KnownPii:
    """Same shape as `customers.service.build_known_pii`, repeated here because
    `conversation` may not import a service that reaches a repository."""
    words: dict[str, None] = {}
    for full in (first_name, last_name):
        for word in (full or "").split():
            if len(word) >= 3:
                words.setdefault(word, None)
    return KnownPii(document_number=(document_number or "").strip() or None, names=tuple(words))


class FakeBank:
    """`BankReadTools` bound to one `ToolContext` over CSVs under `data_dir`."""

    def __init__(
        self, ctx: ToolContext, data_dir: Path, overlay: FakeBankOverlay | None = None
    ) -> None:
        self._ctx = ctx
        self._customers_csv = data_dir / "customers.csv"
        self._products_csv = data_dir / "products.csv"
        self._transactions_glob = data_dir / "transactions" / "**" / "*.csv"
        self._complaints_dir = data_dir / "complaints"
        self._complaints_glob = self._complaints_dir / "**" / "*.csv"
        self._fx_rates_csv = data_dir / "daily_exchange_rates.csv"
        # A caller with no session-wide overlay (a one-off read) gets its own,
        # empty one rather than a required argument every read-only call site
        # would otherwise have to pass (D7).
        self._overlay = overlay if overlay is not None else FakeBankOverlay()

    async def _query(self, sql: str, params: list[Any]) -> list[dict[str, Any]]:
        try:
            return await asyncio.to_thread(_run_query, sql, params)
        except duckdb.Error as exc:
            raise ToolUnavailable(f"fakebank query failed: {exc}") from exc

    async def get_profile(self) -> CustomerProfile:
        rows = await self._query(
            f"""
            SELECT country, customer_status, first_name, city
            FROM read_csv({_sql_literal(self._customers_csv)}, all_varchar=true)
            WHERE customer_id = ?
            """,
            [self._ctx.customer_id],
        )
        if not rows:
            raise ToolUnavailable(f"no profile for customer {self._ctx.customer_id!r}")
        row = rows[0]
        country = _COUNTRY_LABELS.get(row["country"])
        if country is None:
            raise ToolUnavailable(f"unknown country {row['country']!r}")
        return CustomerProfile(
            country=country,
            customer_status=row["customer_status"],
            first_name=(row["first_name"] or "").strip() or None,
            city=(row["city"] or "").strip() or None,
        )

    async def get_pii_profile(self) -> KnownPii:
        rows = await self._query(
            f"""
            SELECT document_number, first_name, last_name
            FROM read_csv({_sql_literal(self._customers_csv)}, all_varchar=true)
            WHERE customer_id = ?
            """,
            [self._ctx.customer_id],
        )
        if not rows:
            raise ToolUnavailable(f"no profile for customer {self._ctx.customer_id!r}")
        row = rows[0]
        return _known_pii(row["document_number"], row["first_name"], row["last_name"])

    async def list_cards(self) -> list[CardSummary]:
        rows = await self._query(
            f"""
            SELECT product_id, product_type, right(product_number, 4) AS last4,
                   product_status
            FROM read_csv({_sql_literal(self._products_csv)}, all_varchar=true)
            WHERE customer_id = ?
              AND product_type IN ('Tarjeta Crédito', 'Tarjeta Débito')
            """,
            [self._ctx.customer_id],
        )
        return [self._to_summary(row) for row in rows]

    async def get_card_details(self, card_id: str) -> CardDetails:
        rows = await self._query(
            f"""
            SELECT product_id, product_type,
                   right(product_number, 4) AS last4, currency,
                   CAST(NULLIF(current_balance, '') AS DECIMAL(18,2)) AS current_balance,
                   CAST(NULLIF(credit_limit, '') AS DECIMAL(18,2)) AS credit_limit,
                   CAST(NULLIF(interest_rate, '') AS DECIMAL(9,4)) AS interest_rate,
                   CAST(NULLIF(expiration_date, '') AS DATE) AS expiration_date,
                   product_status,
                   CAST(NULLIF(days_past_due, '') AS INTEGER) AS days_past_due
            FROM read_csv({_sql_literal(self._products_csv)}, all_varchar=true)
            WHERE product_id = ? AND customer_id = ?
            """,
            [card_id, self._ctx.customer_id],
        )
        if rows and rows[0]["product_type"] not in _CARD_KINDS:
            # Owned, but not a card (e.g. a savings account): R1 is satisfied
            # (it is this customer's own product), it just isn't a card.
            raise NotFound(f"no card {card_id!r}")
        if not rows:
            if await self._probe_card_exists(card_id):
                raise AccessDenied(f"card {card_id!r} does not belong to this customer")
            raise NotFound(f"no card {card_id!r}")
        row = rows[0]
        summary = self._to_summary(row)
        is_debit = summary.kind == "debit"
        return CardDetails(
            **summary.model_dump(),
            currency=row["currency"],
            expiration_date=row["expiration_date"],
            credit_limit=None if is_debit else row["credit_limit"],
            current_balance=row["current_balance"],
            interest_rate=None if is_debit else row["interest_rate"],
            days_past_due=None if is_debit else row["days_past_due"],
            source=f"bank.products:{row['product_id']}",
        )

    async def _probe_card_exists(self, card_id: str) -> bool:
        """Whether `card_id` is *someone else's* card (D17 R1 hardening).

        Selects only `product_type`, never a balance, limit, card number or
        other customer's id: enough to tell "belongs to another customer"
        (`AccessDenied`) apart from "doesn't exist, or isn't a card"
        (`NotFound`), and nothing more.
        """
        rows = await self._query(
            f"""
            SELECT product_type
            FROM read_csv({_sql_literal(self._products_csv)}, all_varchar=true)
            WHERE product_id = ?
            """,
            [card_id],
        )
        return bool(rows) and rows[0]["product_type"] in _CARD_KINDS

    async def search_transactions(self, tx_filter: TxFilter) -> list[TxView]:
        if tx_filter.card_id is not None:
            # Reuses the ownership check above: NotFound for an unknown or
            # non-card id, AccessDenied for another customer's card (D17).
            await self.get_card_details(tx_filter.card_id)
        sql, params = self._build_tx_query(tx_filter)
        rows = await self._query(sql, params)
        return [self._to_tx_view(row) for row in rows]

    async def explain_decline(self, tx_id: str) -> DeclineExplanation:
        """`transactions.explain_decline` (D4, R1): this customer's own
        Declined transaction only. Unlike `get_transactions_by_ids`, there is
        no `AccessDenied` path and no existence probe -- a foreign or
        missing id is `NotFound` either way, so explaining a decline never
        confirms that some other customer's transaction exists.
        """
        rows = await self._query(
            f"""
            SELECT transaction_id, product_id,
                   CAST(transaction_date AS TIMESTAMP) AS occurred_at,
                   CAST(amount AS DECIMAL(18,2)) AS amount, currency,
                   CAST(NULLIF(amount_usd, '') AS DECIMAL(18,2)) AS amount_usd,
                   transaction_type, NULLIF(transaction_category, '') AS transaction_category,
                   NULLIF(merchant_name, '') AS merchant_name,
                   NULLIF(merchant_category, '') AS merchant_category,
                   channel, NULLIF(transaction_city, '') AS transaction_city,
                   NULLIF(transaction_country, '') AS transaction_country,
                   transaction_status, NULLIF(response_code, '') AS response_code,
                   CAST(NULLIF(fraud_score, '') AS DECIMAL(9,4)) AS fraud_score
            FROM read_csv({_sql_literal(self._transactions_glob)},
                          hive_partitioning=true, union_by_name=true, all_varchar=true)
            WHERE customer_id = ? AND transaction_id = ?
            """,
            [self._ctx.customer_id, tx_id],
        )
        if not rows or rows[0]["transaction_status"] != "Declined":
            raise NotFound(f"no declined transaction {tx_id!r}")
        tx = self._to_tx_view(rows[0])
        code = lookup_decline_code(tx.response_code)
        return DeclineExplanation(
            code=tx.response_code or "",
            cause_key=code.cause_key,
            next_step_key=code.next_step_key,
            self_service=code.self_service,
            source=f"policy:decline_codes@{self._ctx.policy_version}",
        )

    async def get_transactions_by_ids(self, tx_ids: list[str]) -> list[TxView]:
        """`tx_ids`' own rows, in the same order (D4-B, `disputes.create_claim`'s
        own-row check, R1). The card `get_card_details`/`_probe_card_exists`
        shape, minus the card/non-card distinction: every transaction row
        already is a transaction, so the probe below selects only the id
        itself, no data column.
        """
        placeholders = ", ".join("?" for _ in tx_ids)
        rows = await self._query(
            f"""
            SELECT transaction_id, product_id,
                   CAST(transaction_date AS TIMESTAMP) AS occurred_at,
                   CAST(amount AS DECIMAL(18,2)) AS amount, currency,
                   CAST(NULLIF(amount_usd, '') AS DECIMAL(18,2)) AS amount_usd,
                   transaction_type, NULLIF(transaction_category, '') AS transaction_category,
                   NULLIF(merchant_name, '') AS merchant_name,
                   NULLIF(merchant_category, '') AS merchant_category,
                   channel, NULLIF(transaction_city, '') AS transaction_city,
                   NULLIF(transaction_country, '') AS transaction_country,
                   transaction_status, NULLIF(response_code, '') AS response_code,
                   CAST(NULLIF(fraud_score, '') AS DECIMAL(9,4)) AS fraud_score
            FROM read_csv({_sql_literal(self._transactions_glob)},
                          hive_partitioning=true, union_by_name=true, all_varchar=true)
            WHERE customer_id = ? AND transaction_id IN ({placeholders})
            """,
            [self._ctx.customer_id, *tx_ids],
        )
        by_id = {row["transaction_id"]: row for row in rows}
        missing = [tx_id for tx_id in tx_ids if tx_id not in by_id]
        if missing:
            if await self._probe_transactions_exist(missing):
                raise AccessDenied(f"transaction {missing[0]!r} does not belong to this customer")
            raise NotFound(f"no transaction {missing[0]!r}")
        return [self._to_tx_view(by_id[tx_id]) for tx_id in tx_ids]

    async def _probe_transactions_exist(self, tx_ids: list[str]) -> bool:
        """Whether any of `tx_ids` exists *at all*, regardless of owner (D17
        R1 hardening). Selects only `transaction_id` -- no data column.
        """
        placeholders = ", ".join("?" for _ in tx_ids)
        rows = await self._query(
            f"""
            SELECT transaction_id
            FROM read_csv({_sql_literal(self._transactions_glob)},
                          hive_partitioning=true, union_by_name=true, all_varchar=true)
            WHERE transaction_id IN ({placeholders})
            """,
            list(tx_ids),
        )
        return bool(rows)

    def _build_tx_query(self, tx_filter: TxFilter) -> tuple[str, list[Any]]:
        conditions = ["customer_id = ?"]
        params: list[Any] = [self._ctx.customer_id]
        if tx_filter.card_id is not None:
            conditions.append("product_id = ?")
            params.append(tx_filter.card_id)
        if tx_filter.date_from is not None:
            conditions.append("CAST(transaction_date AS DATE) >= ?")
            params.append(tx_filter.date_from)
        if tx_filter.date_to is not None:
            conditions.append("CAST(transaction_date AS DATE) <= ?")
            params.append(tx_filter.date_to)
        if tx_filter.currency is not None:
            conditions.append("currency = ?")
            params.append(tx_filter.currency)
        if tx_filter.amount_min is not None:
            conditions.append("CAST(amount AS DECIMAL(18,2)) >= ?")
            params.append(tx_filter.amount_min)
        if tx_filter.amount_max is not None:
            conditions.append("CAST(amount AS DECIMAL(18,2)) <= ?")
            params.append(tx_filter.amount_max)
        if tx_filter.status:
            placeholders = ", ".join("?" for _ in tx_filter.status)
            conditions.append(f"transaction_status IN ({placeholders})")
            params.extend(tx_filter.status)
        if tx_filter.merchant_names:
            placeholders = ", ".join("?" for _ in tx_filter.merchant_names)
            conditions.append(f"merchant_name IN ({placeholders})")
            params.extend(tx_filter.merchant_names)
        where_clause = " AND ".join(conditions)
        sql = f"""
            SELECT transaction_id, product_id,
                   CAST(transaction_date AS TIMESTAMP) AS occurred_at,
                   CAST(amount AS DECIMAL(18,2)) AS amount, currency,
                   CAST(NULLIF(amount_usd, '') AS DECIMAL(18,2)) AS amount_usd,
                   transaction_type, NULLIF(transaction_category, '') AS transaction_category,
                   NULLIF(merchant_name, '') AS merchant_name,
                   NULLIF(merchant_category, '') AS merchant_category,
                   channel, NULLIF(transaction_city, '') AS transaction_city,
                   NULLIF(transaction_country, '') AS transaction_country,
                   transaction_status, NULLIF(response_code, '') AS response_code,
                   CAST(NULLIF(fraud_score, '') AS DECIMAL(9,4)) AS fraud_score
            FROM read_csv({_sql_literal(self._transactions_glob)},
                          hive_partitioning=true, union_by_name=true, all_varchar=true)
            WHERE {where_clause}
            ORDER BY occurred_at DESC
            LIMIT 10
        """
        return sql, params

    def _to_summary(self, row: dict[str, Any]) -> CardSummary:
        card_id = row["product_id"]
        status = row["product_status"]
        if card_id in self._overlay.blocked:
            # A session block overrides the dataset status regardless of
            # what it was (D7, D8 `customer_block`).
            status = "Blocked"
        return CardSummary(
            card_id=card_id,
            kind=_CARD_KINDS[row["product_type"]],
            last4=row["last4"],
            status=status,
            locked=card_id in self._overlay.locked,
        )

    async def get_fx_rate(self, source: str, target: str) -> FxRate:
        # Reference data (D3): no `customer_id` filter, unlike every query above.
        rows = await self._query(
            f"""
            SELECT date, exchange_rate
            FROM read_csv({_sql_literal(self._fx_rates_csv)}, all_varchar=true)
            WHERE source_currency = ? AND target_currency = ?
            ORDER BY CAST(date AS DATE) DESC
            LIMIT 1
            """,
            [source, target],
        )
        if not rows:
            raise NotFound(f"no fx rate for {source!r} -> {target!r}")
        row = rows[0]
        return FxRate(
            source=source,
            target=target,
            rate=Decimal(row["exchange_rate"]),
            as_of=date.fromisoformat(row["date"]),
        )

    async def get_card_requests(self) -> list[CustomerCardRequest]:
        """The overlay's requests, newest first, at most 3 (the Postgres read's
        shape). A test may seed `decision`, `credit_limit`, `decided_at`."""
        rows = sorted(
            self._overlay.card_requests.values(), key=lambda r: r["created_at"], reverse=True
        )
        return [
            CustomerCardRequest(
                reference=r["reference"],
                kind=r["kind"],
                card_kind=r["card_kind"],
                status=r["status"],
                decision=r.get("decision"),
                product_id=r.get("product_id"),
                credit_limit=r.get("credit_limit"),
                created_at=r["created_at"],
                decided_at=r.get("decided_at"),
            )
            for r in rows[:3]
        ]

    async def get_priority_signals(self) -> PrioritySignals:
        """B2's two priority signals over the complaints partitions (R1): no
        complaints files at all -- no customer has ever filed one in this
        fixture/sandbox -- means both flags are `False`, never a DuckDB glob
        error."""
        if not list(self._complaints_dir.rglob("*.csv")):
            return PrioritySignals(repeat_complainer=False, open_critical=False)
        open_statuses = load_disputes_policy().priority.open_statuses
        rows = await self._query(
            f"""
            SELECT is_repeat_complainer, priority, status
            FROM read_csv({_sql_literal(self._complaints_glob)},
                          hive_partitioning=true, union_by_name=true, all_varchar=true)
            WHERE customer_id = ?
            """,
            [self._ctx.customer_id],
        )
        repeat_complainer = any(row["is_repeat_complainer"] == "true" for row in rows)
        open_critical = any(
            row["priority"] == "Critical" and row["status"] in open_statuses for row in rows
        )
        return PrioritySignals(repeat_complainer=repeat_complainer, open_critical=open_critical)

    @staticmethod
    def _to_tx_view(row: dict[str, Any]) -> TxView:
        # DuckDB's `CAST(... AS TIMESTAMP)` returns a naive datetime; every
        # `bank.*` timestamp is UTC (`03` §5), so it's attached here rather
        # than left for `TxView`'s `AwareDatetime` to reject outright (D4-B,
        # first real caller of `search_transactions`/`get_transactions_by_ids`
        # to build a `TxView` from this query shape).
        occurred_at = row["occurred_at"]
        if occurred_at.tzinfo is None:
            occurred_at = occurred_at.replace(tzinfo=UTC)
        return TxView(
            tx_id=row["transaction_id"],
            card_id=row["product_id"],
            occurred_at=occurred_at,
            amount=row["amount"],
            currency=row["currency"],
            amount_usd=row["amount_usd"],
            type=row["transaction_type"],
            category=row["transaction_category"],
            merchant_name=row["merchant_name"],
            merchant_category=row["merchant_category"],
            channel=row["channel"],
            city=row["transaction_city"],
            country=row["transaction_country"],
            status=row["transaction_status"],
            response_code=row["response_code"],
            fraud_score=row["fraud_score"],
        )


class FakeBankWrites:
    """`BankWriteTools` bound to one `ToolContext`, backed by a `FakeBankOverlay`
    shared with the session's `FakeBank` reads (D7, D2-K's write contracts).

    Every write first runs `self._reads.get_card_details(card_id)`: the same
    two-query ownership probe reads use (`WHERE product_id = ? AND
    customer_id = ?` on a card type, then the narrower probe on a `NotFound`),
    so `AccessDenied`/`NotFound` come from the exact same rule reads use, and
    nothing is mutated until it passes (R1). Each write then mutates the
    overlay and re-reads it to build `ActionResult.readback`, only reporting
    `verified=True` when the re-read shows what was written (R3).
    """

    def __init__(self, ctx: ToolContext, data_dir: Path, overlay: FakeBankOverlay) -> None:
        self._ctx = ctx
        self._overlay = overlay
        self._reads = FakeBank(ctx, data_dir, overlay)

    async def get_block_origin(self, card_id: str) -> BlockOrigin:
        # Ownership probe first (R1); its result also feeds the bank-side
        # checks below, so it is not discarded.
        details = await self._reads.get_card_details(card_id)
        if card_id in self._overlay.blocked:
            return BlockOrigin(kind="customer_block", reason=None)
        if card_id in self._overlay.locked:
            return BlockOrigin(kind="customer_lock", reason=None)
        profile = await self._reads.get_profile()
        if profile.customer_status != "Active":
            return BlockOrigin(kind="bank_side", reason="customer_status")
        if details.days_past_due is not None and details.days_past_due > 0:
            return BlockOrigin(kind="bank_side", reason="past_due")
        if details.status in ("Blocked", "Suspended"):
            return BlockOrigin(kind="bank_side", reason="bank_status")
        return BlockOrigin(kind="none", reason=None)

    async def lock_card(self, card_id: str, *, idempotency_key: str) -> ActionResult:
        if idempotency_key in self._overlay.results:  # D11 replay: nothing mutated
            return self._overlay.results[idempotency_key]
        await self._reads.get_card_details(card_id)  # ownership probe (R1)
        self._overlay.locked.add(card_id)
        result = self._lock_readback("cards.lock_card", card_id, expected_locked=True)
        self._overlay.results[idempotency_key] = result
        return result

    async def unlock_card(self, card_id: str, *, idempotency_key: str) -> ActionResult:
        if idempotency_key in self._overlay.results:  # D11 replay: nothing mutated
            return self._overlay.results[idempotency_key]
        await self._reads.get_card_details(card_id)  # ownership probe (R1)
        self._overlay.locked.discard(card_id)
        result = self._lock_readback("cards.unlock_card", card_id, expected_locked=False)
        self._overlay.results[idempotency_key] = result
        return result

    def _lock_readback(self, tool: str, card_id: str, *, expected_locked: bool) -> ActionResult:
        locked = card_id in self._overlay.locked  # re-read (R3)
        return ActionResult(
            tool=tool,
            status="applied",
            verified=locked == expected_locked,
            readback={"locked": locked, "at": datetime.now(UTC)},
        )

    async def block_card(
        self, card_id: str, reason: BlockReason, *, idempotency_key: str
    ) -> ActionResult:
        # `reason` picks the reply template upstream (D11); the fake dataset
        # has no column to record it in, so the read-back doesn't carry it.
        if idempotency_key in self._overlay.results:  # D11 replay: nothing mutated
            return self._overlay.results[idempotency_key]
        await self._reads.get_card_details(card_id)  # ownership probe (R1)
        self._overlay.blocked.add(card_id)
        blocked = card_id in self._overlay.blocked  # re-read (R3)
        result = ActionResult(
            tool="cards.block_card",
            status="applied",
            verified=blocked,
            readback={"status": "Blocked" if blocked else "unknown", "at": datetime.now(UTC)},
        )
        self._overlay.results[idempotency_key] = result
        return result

    async def order_replacement(
        self, card_id: str, address_ref: AddressRef, *, idempotency_key: str
    ) -> ActionResult:
        # `address_ref` is `"on_file"` or a vault token (`⟨ADDR_n⟩`, R5): the
        # fake has nowhere to ship to, so it only records the tracking id.
        if idempotency_key in self._overlay.results:  # D11 replay: nothing mutated
            return self._overlay.results[idempotency_key]
        await self._reads.get_card_details(card_id)  # ownership probe (R1)
        tracking_id = "RPL-" + secrets.token_hex(4).upper()
        self._overlay.replacements[card_id] = tracking_id
        ordered = self._overlay.replacements.get(card_id) == tracking_id  # re-read (R3)
        result = ActionResult(
            tool="cards.order_replacement",
            status="applied",
            verified=ordered,
            readback={"status": "ordered" if ordered else "unknown", "at": datetime.now(UTC)},
            tracking_id=tracking_id,
        )
        self._overlay.results[idempotency_key] = result
        return result

    async def request_card(
        self,
        kind: Literal["credit", "debit"],
        changed_fields: list[str],
        *,
        idempotency_key: str,
    ) -> ActionResult:
        if idempotency_key in self._overlay.results:  # D11 replay: nothing mutated
            return self._overlay.results[idempotency_key]
        values = await self._overlay.vault.form_values(changed_fields)
        reference = "CRQ-" + secrets.token_hex(4).upper()
        if set(values) != set(changed_fields):
            # A field the form never staged: nothing is written (R3).
            result = ActionResult(
                tool="cards.request_card",
                status="applied",
                verified=False,
                readback={"status": "unknown", "kind": kind, "at": datetime.now(UTC)},
                tracking_id=reference,
            )
            self._overlay.results[idempotency_key] = result
            return result
        now = datetime.now(UTC)
        for name, value in values.items():
            self._overlay.profile_history.append(
                {
                    "field": name,
                    "old": self._overlay.profile.get(name),
                    "new": value,
                    "actor": "customer",
                    "at": now,
                }
            )
            self._overlay.profile[name] = value
        request_id = uuid4()
        self._overlay.card_requests[request_id] = {
            "reference": reference,
            "kind": "open",
            "card_kind": kind,
            "status": "pending",
            "changed_fields": list(changed_fields),
            "product_id": None,
            "reason_code": None,
            "created_at": now,
        }
        stored = self._overlay.card_requests.get(request_id)  # re-read (R3)
        verified = (
            stored is not None
            and stored["reference"] == reference
            and stored["card_kind"] == kind
            and stored["status"] == "pending"
            and all(self._overlay.profile.get(n) == v for n, v in values.items())
        )
        result = ActionResult(
            tool="cards.request_card",
            status="applied",
            verified=verified,
            # `ReadbackValue` has no list member: `fields_saved` is comma-joined.
            readback={
                "status": "pending" if verified else "unknown",
                "kind": kind,
                "fields_saved": ",".join(changed_fields),
                "request_id": str(request_id),
                "at": now,
            },
            tracking_id=reference,
        )
        self._overlay.results[idempotency_key] = result
        return result

    async def request_closure(
        self, card_id: str, reason: str, *, idempotency_key: str
    ) -> ActionResult:
        if idempotency_key in self._overlay.results:  # D11 replay: nothing mutated
            return self._overlay.results[idempotency_key]
        details = await self._reads.get_card_details(card_id)  # ownership probe (R1)
        reference = "CRQ-" + secrets.token_hex(4).upper()
        now = datetime.now(UTC)
        request_id = uuid4()
        self._overlay.card_requests[request_id] = {
            "reference": reference,
            "kind": "close",
            "card_kind": details.kind,
            "status": "pending",
            "changed_fields": [],
            "product_id": card_id,
            "reason_code": reason,
            "created_at": now,
        }
        stored = self._overlay.card_requests.get(request_id)  # re-read (R3)
        verified = (
            stored is not None
            and stored["reference"] == reference
            and stored["kind"] == "close"
            and stored["status"] == "pending"
            and stored["product_id"] == card_id
            and stored["reason_code"] == reason
        )
        result = ActionResult(
            tool="cards.request_closure",
            status="applied",
            verified=verified,
            readback={
                "status": "pending" if verified else "unknown",
                "reason": reason,
                "request_id": str(request_id),
                "card_id": card_id,
                "card_kind": details.kind,
                "last4": details.last4,
                "current_balance": details.current_balance,  # raw: code formats it (R4)
                "currency": details.currency,
                "at": now,
            },
            tracking_id=reference,
        )
        self._overlay.results[idempotency_key] = result
        return result

    async def pending_card_requests(self) -> PendingCardRequests:
        pending = [r for r in self._overlay.card_requests.values() if r["status"] == "pending"]
        return PendingCardRequests(
            open_pending=any(r["kind"] == "open" for r in pending),
            close_card_ids=frozenset(
                r["product_id"] for r in pending if r["kind"] == "close" and r["product_id"]
            ),
        )

    async def create_claim(
        self,
        tx_ids: list[str],
        answers: list[str],
        priority_flags: list[str],
        *,
        idempotency_key: str,
    ) -> ActionResult:
        # `answers` is only the code-built `bank.complaints.description`
        # (D14) the Postgres path writes; the fake dataset has no complaints
        # table to hold it.
        if idempotency_key in self._overlay.results:  # D11/D15 replay: nothing mutated
            return self._overlay.results[idempotency_key]
        transactions = await self._reads.get_transactions_by_ids(tx_ids)  # ownership probe (R1)
        case_ids = ["CLM-" + secrets.token_hex(4).upper() for _ in transactions]
        priority: Literal["High"] | None = "High" if priority_flags else None
        for case_id in case_ids:
            self._overlay.claim_priorities[case_id] = priority
        result = ActionResult(
            tool="disputes.create_claim",
            status="applied",
            verified=len(case_ids) == len(tx_ids),
            readback={"status": "Open", "count": len(case_ids), "at": datetime.now(UTC)},
            case_ids=case_ids,
        )
        self._overlay.results[idempotency_key] = result
        return result


def make_fakebank_factory(data_dir: Path) -> tuple[BankToolsFactory, BankWriteToolsFactory]:
    """Close over `data_dir` and one shared `FakeBankOverlay` (D7), so the
    registry can bind just a `ToolContext` to each factory (D1, D2, D2-K).
    Callers make one `(read, write)` pair per session: two pairs would each
    get their own overlay and stop seeing each other's writes.
    """
    overlay = FakeBankOverlay()

    def read_factory(ctx: ToolContext) -> BankReadTools:
        return FakeBank(ctx, data_dir, overlay)

    def write_factory(ctx: ToolContext) -> BankWriteTools:
        return FakeBankWrites(ctx, data_dir, overlay)

    return read_factory, write_factory
