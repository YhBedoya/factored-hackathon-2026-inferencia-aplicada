"""Integration fixtures: a throwaway Postgres database and Redis isolation.

Not autouse (D19): a test that doesn't ask for `it_db`/`it_env` (for example
`test_personas.py`, which only reads `latam_golden`) is unaffected.

`it_db` is session-scoped so the migration + fixture load runs once per test
session, not once per test. `it_env` is function-scoped: it points
`Settings`/`get_engine`/`get_redis` at the throwaway database for the
duration of one test, then restores the process to talking to the real dev
stack again.

See `docs/specs/d2-a-login-read-tools-api.md` D19, D11, D12.
"""

import asyncio
import os
import secrets
import subprocess
import uuid
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.config import get_settings
from app.core.db import get_engine
from app.core.redis import get_redis, ping_redis
from app.domains.identity.passwords import hash_password, login_key
from app.main import create_app

__all__ = ["ItAccount", "app_client", "it_accounts", "it_db", "it_env"]

_CONNECT_TIMEOUT_SECONDS = 2
_BACKEND_DIR = Path(__file__).resolve().parents[2]
_FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "fakebank"
_DB_PREFIX = "latam_it_"
# rl:login:<key>, turn:<id>, conv:<id> (D19, D14, D7): no product-code prefix,
# so cleanup targets exactly the key shapes the app itself writes.
_REDIS_KEY_PATTERNS = ("rl:login:*", "turn:*", "conv:*")

# The three fixture customers loaded by `_load_fixtures` (D19): `document_type`
# and `document_number` as `customers.csv` has them, not yet normalized.
_FIXTURE_DOCUMENTS: dict[str, tuple[str, str]] = {
    "CLI-TFMULTI00001": ("CC", "DOC-TF0000001"),
    "CLI-TFSINGLE0002": ("CC", "DOC-TF0000002"),
    "CLI-TFBLOCKD0003": ("CC", "DOC-TF0000003"),
}


@dataclass(frozen=True)
class ItAccount:
    """One `it_accounts` login, in-test only (D19): not the seeded D4
    generator, which needs a `CREDENTIALS_SEED` this fixture doesn't use.
    """

    document_type: str
    document_number: str
    password: str


def _psycopg_dsn(database_url: str, dbname: str) -> str:
    """`DATABASE_URL` (`postgresql+asyncpg://...`) -> a psycopg3 DSN on `dbname`."""
    base = database_url.replace("postgresql+asyncpg://", "postgresql://")
    host_part = base.rpartition("/")[0]
    return f"{host_part}/{dbname}"


def _asyncpg_url(database_url: str, dbname: str) -> str:
    """`DATABASE_URL`, but pointed at `dbname` instead. Keeps the `+asyncpg` driver."""
    host_part = database_url.rpartition("/")[0]
    return f"{host_part}/{dbname}"


def _copy_csv(conn: psycopg.Connection, path: Path, table: str) -> None:
    """`COPY path -> table`, with the column list read from the CSV header.

    The header is decoded as `utf-8-sig` only to strip a leading BOM from the
    first column name; the data rows are streamed to `COPY` as raw bytes,
    since `HEADER true` already tells Postgres to skip the header line
    regardless of its own encoding quirks (D19).
    """
    with path.open(encoding="utf-8-sig", newline="") as header_file:
        header = header_file.readline().rstrip("\r\n")
    columns = ", ".join(header.split(","))
    copy_sql = f"COPY {table} ({columns}) FROM STDIN (FORMAT csv, HEADER true, NULL '')"
    with conn.cursor() as cur, path.open("rb") as data_file, cur.copy(copy_sql) as copy:
        while chunk := data_file.read(1 << 16):
            copy.write(chunk)


def _load_fixtures(psycopg_dsn: str) -> None:
    with psycopg.connect(psycopg_dsn, autocommit=True) as conn:
        _copy_csv(conn, _FIXTURES_DIR / "customers.csv", "bank.customers")
        _copy_csv(conn, _FIXTURES_DIR / "products.csv", "bank.products")
        for path in sorted((_FIXTURES_DIR / "transactions").rglob("*.csv")):
            _copy_csv(conn, path, "bank.transactions")


@pytest.fixture(scope="session")
def it_db() -> Iterator[str]:
    """A migrated, seeded `latam_it_<hex>` database. Yields its asyncpg URL."""
    database_url = get_settings().database_url
    maintenance_dsn = _psycopg_dsn(database_url, "postgres")
    try:
        with psycopg.connect(maintenance_dsn, connect_timeout=_CONNECT_TIMEOUT_SECONDS) as conn:
            conn.execute("SELECT 1")
    except psycopg.OperationalError:
        pytest.skip("Postgres is not reachable from the host DATABASE_URL")

    db_name = f"{_DB_PREFIX}{secrets.token_hex(4)}"
    with psycopg.connect(maintenance_dsn, autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{db_name}"')

    it_database_url = _asyncpg_url(database_url, db_name)
    subprocess.run(
        ["uv", "run", "alembic", "upgrade", "head"],
        cwd=_BACKEND_DIR,
        env={**os.environ, "DATABASE_URL": it_database_url},
        check=True,
        capture_output=True,
        text=True,
    )
    _load_fixtures(_psycopg_dsn(it_database_url, db_name))

    yield it_database_url

    if not db_name.startswith(_DB_PREFIX):
        raise RuntimeError(f"refusing to drop database {db_name!r}: not a test database")
    with psycopg.connect(maintenance_dsn, autocommit=True) as conn:
        conn.execute(f'DROP DATABASE "{db_name}" WITH (FORCE)')


async def _delete_matching_redis_keys() -> None:
    """Delete every key this run could have created. Not best-effort: once
    `it_env` has confirmed Redis is reachable, a failure here is a real bug
    (e.g. a key shape drifted), not something to swallow.
    """
    redis = get_redis()
    for pattern in _REDIS_KEY_PATTERNS:
        keys = [key async for key in redis.scan_iter(match=pattern)]
        if keys:
            await redis.delete(*keys)


@pytest.fixture
def it_env(it_db: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Point `Settings`/`get_engine`/`get_redis` at the throwaway database.

    Redis itself is the real dev instance (no throwaway Redis): isolation
    comes from the per-run `IDENTITY_HMAC_KEY` and fresh UUIDs each test
    generates, which keep its keys from colliding with another run's, plus
    the teardown below deleting the key shapes the app writes (D19). Skips,
    like `it_db` does for Postgres, when Redis isn't reachable from the host
    `REDIS_URL` (the dev compose overlay publishes it on `127.0.0.1:6379`).
    """
    monkeypatch.setenv("DATABASE_URL", it_db)
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("BANK", "postgres")
    monkeypatch.setenv("JWT_SECRET", secrets.token_urlsafe(32))
    monkeypatch.setenv("IDENTITY_HMAC_KEY", secrets.token_urlsafe(32))
    monkeypatch.setenv("CREDENTIALS_SEED", secrets.token_urlsafe(32))
    get_settings.cache_clear()
    get_engine.cache_clear()
    get_redis.cache_clear()

    # `get_redis()` is loop-bound (state file conventions): the client
    # `ping_redis()` builds belongs to *this* `asyncio.run()`'s loop, so it
    # must not survive past it -- clear it again whether or not Redis
    # answered, so the test body builds its own client in its own loop.
    reachable = asyncio.run(ping_redis())
    get_redis.cache_clear()
    if not reachable:
        get_settings.cache_clear()
        get_engine.cache_clear()
        pytest.skip("Redis is not reachable from the host REDIS_URL")

    yield

    get_redis.cache_clear()  # drop whatever client the test body's own loop built
    asyncio.run(_delete_matching_redis_keys())
    get_settings.cache_clear()
    get_engine.cache_clear()
    get_redis.cache_clear()


async def _insert_accounts(accounts: dict[str, ItAccount]) -> None:
    async with get_engine().begin() as conn:
        for customer_id, account in accounts.items():
            key = login_key(
                account.document_type,
                account.document_number,
                hmac_key=get_settings().identity_hmac_key,
            )
            await conn.execute(
                text(
                    """
                    INSERT INTO identity.accounts
                        (account_id, customer_id, login_key, password_hash)
                    VALUES (:account_id, :customer_id, :login_key, :password_hash)
                    """
                ),
                {
                    "account_id": str(uuid.uuid4()),
                    "customer_id": customer_id,
                    "login_key": key,
                    "password_hash": hash_password(account.password),
                },
            )


async def _delete_accounts(customer_ids: Iterable[str]) -> None:
    async with get_engine().begin() as conn:
        for customer_id in customer_ids:
            await conn.execute(
                text("DELETE FROM identity.accounts WHERE customer_id = :customer_id"),
                {"customer_id": customer_id},
            )


@pytest.fixture
def it_accounts(it_env: None) -> Iterator[dict[str, ItAccount]]:
    """`identity.accounts` rows for the three fixture customers (D19), keyed
    by `customer_id`. Uses the per-run `IDENTITY_HMAC_KEY` `it_env` just set,
    so the `login_key` this fixture writes is the one `POST /auth/login`
    recomputes from the same document at test time.

    Deletes its own rows on teardown (T15): `it_db` is session-scoped, so
    two tests in the same session that both ask for `it_accounts` would
    otherwise collide on `accounts_customer_id_key` the second time around.
    """

    accounts = {
        customer_id: ItAccount(document_type, document_number, f"it-pass-{customer_id.lower()}")
        for customer_id, (document_type, document_number) in _FIXTURE_DOCUMENTS.items()
    }
    asyncio.run(_insert_accounts(accounts))
    # `get_engine()` is loop-bound (state file conventions): this fixture's
    # own `asyncio.run()` leaves a cached engine tied to a loop that is now
    # closed, so `app_client`'s own loop must build its own.
    get_engine.cache_clear()

    yield accounts

    get_engine.cache_clear()
    asyncio.run(_delete_accounts(accounts))
    get_engine.cache_clear()


@pytest.fixture
def app_client(it_env: None) -> Iterator[TestClient]:
    """A `TestClient` for a fresh app, built only after `it_env` has pointed
    `Settings`/`get_engine`/`get_redis` at the throwaway database (D19):
    `create_app()` must run after that monkeypatching, not at import time.
    """

    with TestClient(create_app()) as client:
        yield client
