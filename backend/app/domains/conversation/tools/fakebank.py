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
"""

import asyncio
from pathlib import Path
from typing import Any, Literal

import duckdb

from app.core.errors import AccessDenied, NotFound, ToolUnavailable
from app.domains.cards.schemas import CardDetails, CardSummary
from app.domains.conversation.tools.bank import BankReadTools, BankToolsFactory
from app.domains.conversation.tools.context import ToolContext
from app.domains.customers.schemas import CustomerProfile
from app.domains.transactions.schemas import TxFilter, TxView

__all__ = ["FakeBank", "make_fakebank_factory"]

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


class FakeBank:
    """`BankReadTools` bound to one `ToolContext` over CSVs under `data_dir`."""

    def __init__(self, ctx: ToolContext, data_dir: Path) -> None:
        self._ctx = ctx
        self._customers_csv = data_dir / "customers.csv"
        self._products_csv = data_dir / "products.csv"
        self._transactions_glob = data_dir / "transactions" / "**" / "*.csv"

    async def _query(self, sql: str, params: list[Any]) -> list[dict[str, Any]]:
        try:
            return await asyncio.to_thread(_run_query, sql, params)
        except duckdb.Error as exc:
            raise ToolUnavailable(f"fakebank query failed: {exc}") from exc

    async def get_profile(self) -> CustomerProfile:
        rows = await self._query(
            f"""
            SELECT country, customer_status
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
        return CustomerProfile(country=country, customer_status=row["customer_status"])

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

    @staticmethod
    def _to_summary(row: dict[str, Any]) -> CardSummary:
        return CardSummary(
            card_id=row["product_id"],
            kind=_CARD_KINDS[row["product_type"]],
            last4=row["last4"],
            status=row["product_status"],
            locked=False,
        )

    @staticmethod
    def _to_tx_view(row: dict[str, Any]) -> TxView:
        return TxView(
            tx_id=row["transaction_id"],
            card_id=row["product_id"],
            occurred_at=row["occurred_at"],
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


def make_fakebank_factory(data_dir: Path) -> BankToolsFactory:
    """Close over `data_dir` so the registry can bind just a `ToolContext` (D1, D2)."""

    def factory(ctx: ToolContext) -> BankReadTools:
        return FakeBank(ctx, data_dir)

    return factory
