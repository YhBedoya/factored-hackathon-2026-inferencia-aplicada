"""`uv run python -m app.domains.identity.provision` -- seed `identity.accounts`
into `latam_golden` from `bank.customers` (D3, D4, D5).

Customer-only accounts (D3): every `bank.customers` row gets exactly one
`identity.accounts` row with a deterministic, seeded password (D4) and the
HMAC `login_key` (D2) as its only lookup key -- the raw document number
never reaches `identity.accounts`. A rerun truncates and rewrites inside a
single transaction, so the row count and every generated password come out
the same each time (D5). `data/secrets/credentials.csv` is the one place
the raw document number and password ever touch disk together, and it stays
git-ignored (R10); nothing here prints or logs either value.

Connects with sync `psycopg` (not the app's async engine): this is a
one-shot CLI against `latam_golden`, run from `make seed-identity`/`make
data`, not a request-scoped call (mirrors `pipeline/load/__main__.py` and
`pipeline/load/demo_reset.py`, whose DSN-stripping and transaction shape
this reimplements rather than imports -- this module lives in `backend/`,
`pipeline/` is a separate `uv` project).
"""

from __future__ import annotations

import csv
import os
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import psycopg

from app.core.config import get_settings
from app.domains.identity.passwords import generate_password, hash_password, login_key

# `identity/provision.py` -> `identity/` -> `domains/` -> `app/` -> `backend/` -> repo root.
REPO_ROOT = Path(__file__).resolve().parents[4]
_CREDENTIALS_CSV = REPO_ROOT / "data" / "secrets" / "credentials.csv"

_PBKDF2_ITERATIONS = 1000


def _psycopg_dsn(database_url: str) -> str:
    """SQLAlchemy async URL -> a bare psycopg-compatible DSN.

    Psycopg only understands `postgresql://` (no `+asyncpg` driver suffix).
    """
    parts = urlsplit(database_url)
    return urlunsplit(("postgresql", parts.netloc, parts.path, parts.query, parts.fragment))


def _require_secrets(*, credentials_seed: str, identity_hmac_key: str) -> None:
    """Refuse to run with an empty seed or HMAC key (D5), naming only the
    variable(s) that are actually empty.
    """
    empty = [
        name
        for name, value in (
            ("CREDENTIALS_SEED", credentials_seed),
            ("IDENTITY_HMAC_KEY", identity_hmac_key),
        )
        if not value
    ]
    if empty:
        raise SystemExit(f"refusing to provision: empty {', '.join(empty)}")


def _write_credentials_csv(rows: list[tuple[str, str, str, str]]) -> Path:
    """Write the git-ignored plaintext export, mode `0600` (R10).

    `os.chmod` runs after every write (not just on creation) so a rerun
    never leaves the file world- or group-readable, regardless of the
    process umask or a stale mode from a prior run.
    """
    _CREDENTIALS_CSV.parent.mkdir(parents=True, exist_ok=True)
    with _CREDENTIALS_CSV.open("w", newline="") as f:
        # `csv`'s RFC-mandated default is `\r\n`; this export is read by
        # `head`/`wc` and by developers, not Excel, so plain `\n` is right.
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(["customer_id", "document_type", "document_number", "password"])
        writer.writerows(rows)
    os.chmod(_CREDENTIALS_CSV, 0o600)
    return _CREDENTIALS_CSV


def main() -> None:
    settings = get_settings()
    _require_secrets(
        credentials_seed=settings.credentials_seed,
        identity_hmac_key=settings.identity_hmac_key,
    )

    dsn = _psycopg_dsn(settings.golden_database_url)
    csv_rows: list[tuple[str, str, str, str]] = []
    row_count = 0

    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute("SELECT customer_id, document_type, document_number FROM bank.customers")
        customers = cur.fetchall()

        cur.execute("TRUNCATE identity.accounts")
        with cur.copy(
            "COPY identity.accounts "
            "(account_id, role, customer_id, login_key, password_hash, status) "
            "FROM STDIN"
        ) as copy:
            for customer_id, document_type, document_number in customers:
                password = generate_password(customer_id, seed=settings.credentials_seed)
                copy.write_row(
                    (
                        str(uuid4()),
                        "customer",
                        customer_id,
                        login_key(
                            document_type,
                            document_number,
                            hmac_key=settings.identity_hmac_key,
                        ),
                        hash_password(password, iterations=_PBKDF2_ITERATIONS),
                        "active",
                    )
                )
                csv_rows.append((customer_id, document_type, document_number, password))
                row_count += 1
        # `with psycopg.connect(...)` commits on a clean exit (not
        # autocommit): the TRUNCATE and every COPYed row land in one
        # transaction, so a failure partway through leaves the previous
        # `identity.accounts` state untouched.

    export_path = _write_credentials_csv(csv_rows)
    print(f"identity.accounts: {row_count}")
    print(export_path)


if __name__ == "__main__":
    main()
