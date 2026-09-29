"""D20: `eval/personas.yaml` vs `latam_golden` -- every persona's traits are
checked against real data by that trait's own predicate SQL. Local only
(connects to `latam_golden` itself and skips when it is unreachable) and
uses no `conftest` fixture: it neither builds nor touches the throwaway
`latam_it_<hex>` databases the rest of `tests/integration/` uses.

See `docs/solution-docs/03-data-architecture.md` §8, `eval/personas.yaml`'s
own header comment (the closed trait vocabulary this file implements) and
`docs/specs/d2-a-login-read-tools-api.md` D20.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import psycopg
import pytest
import yaml

from app.core.config import get_settings

# `test_personas.py` -> `integration/` -> `tests/` -> `backend/` -> repo root.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_PERSONAS_YAML = _REPO_ROOT / "eval" / "personas.yaml"

_CARD_TYPES = ("Tarjeta Crédito", "Tarjeta Débito")
_CARD_KIND_BY_TYPE = {"Tarjeta Crédito": "credit", "Tarjeta Débito": "debit"}
_COUNTRY_BY_CODE = {"MX": "México", "CO": "Colombia", "AR": "Argentina"}

# B1/D19's original 10, which D20 requires to stay present.
_ORIGINAL_IDS = {
    "CLI-U6NAXZG11P97",
    "CLI-15CX29YY6SS9",
    "CLI-AO5PZVMZCL1V",
    "CLI-H7CHAE6NGLYQ",
    "CLI-H24P25YVOAJY",
    "CLI-BCWKVTMY5S99",
    "CLI-UZ7Z6C3JFXGX",
    "CLI-8U06DH6VYHA3",
    "CLI-HYFIB9VMDJRR",
    "CLI-2FKTNVMZ3HVH",
}

# Keys that describe a persona but aren't traits with a predicate. T4/D17
# adds `split` (`dev | heldout`): it partitions personas, it doesn't assert
# anything about `latam_golden`.
_NON_TRAIT_KEYS = {"customer_id", "notes", "split"}


def _psycopg_dsn(database_url: str) -> str:
    """SQLAlchemy async URL -> a bare psycopg-compatible DSN (mirrors
    `app.domains.identity.provision._psycopg_dsn`): psycopg only understands
    `postgresql://`, not the `+asyncpg` driver suffix.
    """
    parts = urlsplit(database_url)
    return urlunsplit(("postgresql", parts.netloc, parts.path, parts.query, parts.fragment))


def _check_country(cur: psycopg.Cursor[Any], customer_id: str, value: Any) -> bool:
    cur.execute(
        "SELECT country FROM bank.customers WHERE customer_id = %s",
        (customer_id,),
    )
    row = cur.fetchone()
    return row is not None and row[0] == _COUNTRY_BY_CODE[value]


def _check_card_count(cur: psycopg.Cursor[Any], customer_id: str, value: Any) -> bool:
    cur.execute(
        "SELECT count(*) FROM bank.products WHERE customer_id = %s AND product_type = ANY(%s)",
        (customer_id, list(_CARD_TYPES)),
    )
    row = cur.fetchone()
    return row is not None and row[0] == value


def _check_card_kinds(cur: psycopg.Cursor[Any], customer_id: str, value: Any) -> bool:
    cur.execute(
        "SELECT DISTINCT product_type FROM bank.products "
        "WHERE customer_id = %s AND product_type = ANY(%s)",
        (customer_id, list(_CARD_TYPES)),
    )
    kinds = {_CARD_KIND_BY_TYPE[row[0]] for row in cur.fetchall()}
    return kinds == set(value)


def _check_blocked(cur: psycopg.Cursor[Any], customer_id: str, value: Any) -> bool:
    cur.execute(
        "SELECT EXISTS(SELECT 1 FROM bank.products "
        "WHERE customer_id = %s AND product_type = ANY(%s) AND product_status = 'Blocked')",
        (customer_id, list(_CARD_TYPES)),
    )
    row = cur.fetchone()
    return row is not None and row[0] == value


def _check_customer_status(cur: psycopg.Cursor[Any], customer_id: str, value: Any) -> bool:
    cur.execute(
        "SELECT customer_status FROM bank.customers WHERE customer_id = %s",
        (customer_id,),
    )
    row = cur.fetchone()
    return row is not None and row[0] == value


def _check_missing_income(cur: psycopg.Cursor[Any], customer_id: str, value: Any) -> bool:
    cur.execute(
        "SELECT estimated_monthly_income IS NULL FROM bank.customers WHERE customer_id = %s",
        (customer_id,),
    )
    row = cur.fetchone()
    return row is not None and row[0] == value


def _check_repeat_complainer(cur: psycopg.Cursor[Any], customer_id: str, value: Any) -> bool:
    cur.execute(
        "SELECT EXISTS(SELECT 1 FROM bank.complaints "
        "WHERE customer_id = %s AND is_repeat_complainer = true)",
        (customer_id,),
    )
    row = cur.fetchone()
    return row is not None and row[0] == value


def _check_regulator_case(cur: psycopg.Cursor[Any], customer_id: str, value: Any) -> bool:
    cur.execute(
        "SELECT EXISTS(SELECT 1 FROM bank.complaints "
        "WHERE customer_id = %s AND reception_channel = 'Regulator')",
        (customer_id,),
    )
    row = cur.fetchone()
    return row is not None and row[0] == value


def _check_recent_declines(cur: psycopg.Cursor[Any], customer_id: str, value: Any) -> bool:
    for code in value:
        cur.execute(
            "SELECT EXISTS(SELECT 1 FROM bank.transactions "
            "WHERE customer_id = %s AND transaction_status = 'Declined' AND response_code = %s "
            "AND transaction_date >= "
            "(SELECT load_date FROM app.system_metadata LIMIT 1) - interval '30 days')",
            (customer_id, code),
        )
        row = cur.fetchone()
        if row is None or not row[0]:
            return False
    return True


def _check_has_pending_transaction(cur: psycopg.Cursor[Any], customer_id: str, value: Any) -> bool:
    cur.execute(
        "SELECT EXISTS(SELECT 1 FROM bank.transactions "
        "WHERE customer_id = %s AND transaction_status = 'Pending')",
        (customer_id,),
    )
    row = cur.fetchone()
    return row is not None and row[0] == value


def _check_has_reversed_transaction(cur: psycopg.Cursor[Any], customer_id: str, value: Any) -> bool:
    cur.execute(
        "SELECT EXISTS(SELECT 1 FROM bank.transactions "
        "WHERE customer_id = %s AND transaction_status = 'Reversed')",
        (customer_id,),
    )
    row = cur.fetchone()
    return row is not None and row[0] == value


def _check_expiring_card(cur: psycopg.Cursor[Any], customer_id: str, value: Any) -> bool:
    cur.execute(
        "SELECT EXISTS(SELECT 1 FROM bank.products "
        "WHERE customer_id = %s AND product_type = ANY(%s) AND expiration_date BETWEEN "
        "(SELECT load_date FROM app.system_metadata LIMIT 1) "
        "AND (SELECT load_date FROM app.system_metadata LIMIT 1) + interval '90 days')",
        (customer_id, list(_CARD_TYPES)),
    )
    row = cur.fetchone()
    return row is not None and row[0] == value


def _check_usd_card(cur: psycopg.Cursor[Any], customer_id: str, value: Any) -> bool:
    cur.execute(
        "SELECT EXISTS(SELECT 1 FROM bank.products "
        "WHERE customer_id = %s AND product_type = ANY(%s) AND currency = 'USD')",
        (customer_id, list(_CARD_TYPES)),
    )
    row = cur.fetchone()
    return row is not None and row[0] == value


# The closed trait vocabulary (mirrors `eval/personas.yaml`'s header comment,
# which is the source of truth for what each predicate means).
_TRAIT_CHECKS: dict[str, Callable[[psycopg.Cursor[Any], str, Any], bool]] = {
    "country": _check_country,
    "card_count": _check_card_count,
    "card_kinds": _check_card_kinds,
    "blocked": _check_blocked,
    "customer_status": _check_customer_status,
    "missing_income": _check_missing_income,
    "repeat_complainer": _check_repeat_complainer,
    "regulator_case": _check_regulator_case,
    "recent_declines": _check_recent_declines,
    "has_pending_transaction": _check_has_pending_transaction,
    "has_reversed_transaction": _check_has_reversed_transaction,
    "expiring_card": _check_expiring_card,
    "usd_card": _check_usd_card,
}


def test_personas_match_golden() -> None:
    settings = get_settings()
    dsn = _psycopg_dsn(settings.golden_database_url)
    try:
        conn = psycopg.connect(dsn, connect_timeout=3)
    except psycopg.OperationalError:
        pytest.skip("latam_golden is unreachable")

    with conn:
        personas = yaml.safe_load(_PERSONAS_YAML.read_text())["personas"]
        assert len(personas) >= 28
        ids = {persona["customer_id"] for persona in personas}
        assert _ORIGINAL_IDS <= ids

        with conn.cursor() as cur:
            for persona in personas:
                customer_id = persona["customer_id"]
                for key, value in persona.items():
                    if key in _NON_TRAIT_KEYS:
                        continue
                    check = _TRAIT_CHECKS.get(key)
                    assert check is not None, f"{customer_id}: unknown persona trait {key!r}"
                    assert check(cur, customer_id, value), (
                        f"{customer_id}: trait {key}={value!r} does not hold against latam_golden"
                    )
