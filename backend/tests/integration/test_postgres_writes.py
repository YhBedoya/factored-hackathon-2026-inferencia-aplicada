"""A3 "Done when": Postgres card writes verified from a re-read (R3),
refused for a foreign card (R1), the block + history row in one transaction
(R12), and idempotent under a replayed key (D11).

Fixture customers (`tests/fixtures/fakebank/README.md`): `CLI-TFMULTI00001`
owns `PRD-TFM1CRED0001` (credit) and `PRD-TFM1DEBT0002` (debit);
`CLI-TFSINGLE0002` owns `PRD-TFS2CRED0001`.

See `docs/specs/d3-a-guardrails-write-path.md` D9-D11; §"Test list" ->
`test_postgres_writes.py`.
"""

import asyncio
import secrets
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import text

from app.core.db import get_engine
from app.core.errors import AccessDenied
from app.domains.cards import repository as cards_repository
from app.domains.cards.service import LockState
from app.domains.conversation.tools import postgres_writes
from app.domains.conversation.tools.context import ToolContext
from app.domains.conversation.tools.postgres_writes import PostgresBankWrites

_OWN_CUSTOMER_ID = "CLI-TFMULTI00001"
_OWN_CARD_ID = "PRD-TFM1CRED0001"
_OWN_DEBIT_CARD_ID = "PRD-TFM1DEBT0002"
_FOREIGN_CARD_ID = "PRD-TFS2CRED0001"  # CLI-TFSINGLE0002's card


def _ctx(customer_id: str) -> ToolContext:
    return ToolContext(
        customer_id=customer_id,
        conversation_id=uuid4(),
        actor="customer",
        trace_id="trace-test-postgres-writes",
        policy_version="unversioned",
    )


def _key() -> str:
    return secrets.token_urlsafe(8)


async def _lock_row(card_id: str) -> dict[str, Any]:
    async with get_engine().connect() as conn:
        row = (
            (
                await conn.execute(
                    text(
                        "SELECT locked, updated_at AS at FROM app.card_controls "
                        "WHERE product_id = :card_id"
                    ),
                    {"card_id": card_id},
                )
            )
            .mappings()
            .first()
        )
    assert row is not None
    return {"locked": row["locked"], "at": row["at"]}


async def _block_row(card_id: str) -> dict[str, Any]:
    async with get_engine().connect() as conn:
        row = (
            (
                await conn.execute(
                    text(
                        """
                    SELECT p.product_status AS status,
                           (SELECT at FROM app.card_status_history
                            WHERE product_id = p.product_id
                            ORDER BY at DESC LIMIT 1) AS at
                    FROM bank.products p
                    WHERE p.product_id = :card_id
                    """
                    ),
                    {"card_id": card_id},
                )
            )
            .mappings()
            .first()
        )
    assert row is not None
    return {"status": row["status"], "at": row["at"]}


async def _replacement_row(card_id: str, tracking_id: str) -> dict[str, Any]:
    async with get_engine().connect() as conn:
        row = (
            (
                await conn.execute(
                    text(
                        "SELECT status, created_at AS at FROM app.card_replacements "
                        "WHERE product_id = :card_id AND tracking_id = :tracking_id"
                    ),
                    {"card_id": card_id, "tracking_id": tracking_id},
                )
            )
            .mappings()
            .first()
        )
    assert row is not None
    return {"status": row["status"], "at": row["at"]}


async def _fetch_product_status(card_id: str) -> str:
    async with get_engine().connect() as conn:
        row = (
            (
                await conn.execute(
                    text("SELECT product_status FROM bank.products WHERE product_id = :card_id"),
                    {"card_id": card_id},
                )
            )
            .mappings()
            .first()
        )
    assert row is not None
    status: str = row["product_status"]
    return status


async def _table_count(table: str, card_id: str) -> int:
    async with get_engine().connect() as conn:
        result = await conn.execute(
            text(f"SELECT count(*) FROM {table} WHERE product_id = :card_id"),
            {"card_id": card_id},
        )
        return result.scalar_one()


def test_each_write_verified_from_reread(
    it_env: None, restore_cards: set[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    restore_cards.add(_OWN_CARD_ID)
    writes = PostgresBankWrites(_ctx(_OWN_CUSTOMER_ID))

    async def _stale_get_lock_state(customer_id: str, card_id: str) -> LockState:
        return LockState(locked=False, at=datetime.now(UTC))

    async def _run() -> None:
        lock_result = await writes.lock_card(_OWN_CARD_ID, idempotency_key=_key())
        assert lock_result.verified is True
        assert lock_result.readback == await _lock_row(_OWN_CARD_ID)

        unlock_result = await writes.unlock_card(_OWN_CARD_ID, idempotency_key=_key())
        assert unlock_result.verified is True
        assert unlock_result.readback == await _lock_row(_OWN_CARD_ID)

        block_result = await writes.block_card(
            _OWN_CARD_ID, "lost_or_stolen", idempotency_key=_key()
        )
        assert block_result.verified is True
        assert block_result.readback == await _block_row(_OWN_CARD_ID)

        replacement_result = await writes.order_replacement(
            _OWN_CARD_ID, "on_file", idempotency_key=_key()
        )
        assert replacement_result.verified is True
        assert replacement_result.tracking_id is not None
        assert replacement_result.readback == await _replacement_row(
            _OWN_CARD_ID, replacement_result.tracking_id
        )

        # `get_engine` is loop-bound (state file conventions): the stale
        # re-read runs in this same `asyncio.run()` call, not a second one,
        # so it shares the connection pool the writes above already used.
        monkeypatch.setattr(postgres_writes.cards_service, "get_lock_state", _stale_get_lock_state)
        stale_result = await writes.lock_card(_OWN_CARD_ID, idempotency_key=_key())
        assert stale_result.verified is False

    asyncio.run(_run())


def test_foreign_card_write_refused(it_env: None, restore_cards: set[str]) -> None:
    restore_cards.add(_FOREIGN_CARD_ID)
    writes = PostgresBankWrites(_ctx(_OWN_CUSTOMER_ID))

    async def _run() -> None:
        with pytest.raises(AccessDenied):
            await writes.lock_card(_FOREIGN_CARD_ID, idempotency_key=_key())
        with pytest.raises(AccessDenied):
            await writes.unlock_card(_FOREIGN_CARD_ID, idempotency_key=_key())
        with pytest.raises(AccessDenied):
            await writes.block_card(_FOREIGN_CARD_ID, "lost_or_stolen", idempotency_key=_key())
        with pytest.raises(AccessDenied):
            await writes.order_replacement(_FOREIGN_CARD_ID, "on_file", idempotency_key=_key())

        for table in (
            "app.card_controls",
            "app.card_status_history",
            "app.card_replacements",
        ):
            assert await _table_count(table, _FOREIGN_CARD_ID) == 0

    asyncio.run(_run())


def test_block_history_same_transaction(
    it_env: None, restore_cards: set[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    restore_cards.add(_OWN_CARD_ID)
    restore_cards.add(_OWN_DEBIT_CARD_ID)
    writes = PostgresBankWrites(_ctx(_OWN_CUSTOMER_ID))

    async def _raise_insert(*args: object, **kwargs: object) -> None:
        raise RuntimeError("insert_status_history boom")

    async def _run() -> None:
        result = await writes.block_card(_OWN_CARD_ID, "lost_or_stolen", idempotency_key=_key())
        assert result.verified is True
        assert await _fetch_product_status(_OWN_CARD_ID) == "Blocked"

        async with get_engine().connect() as conn:
            history_rows = (
                (
                    await conn.execute(
                        text(
                            "SELECT old_status, new_status, reason, actor, conversation_id "
                            "FROM app.card_status_history WHERE product_id = :card_id"
                        ),
                        {"card_id": _OWN_CARD_ID},
                    )
                )
                .mappings()
                .all()
            )
        assert len(history_rows) == 1
        row = history_rows[0]
        assert row["new_status"] == "Blocked"
        assert row["reason"] == "lost_or_stolen"
        assert row["actor"] == "customer"
        assert row["conversation_id"] is not None

        # `get_engine` is loop-bound (state file conventions): the forced
        # failure below shares this same `asyncio.run()` call, not a second
        # one, so it reuses the connection pool the block above already used.
        monkeypatch.setattr(cards_repository, "insert_status_history", _raise_insert)
        original_status = await _fetch_product_status(_OWN_DEBIT_CARD_ID)

        with pytest.raises(RuntimeError):
            await writes.block_card(_OWN_DEBIT_CARD_ID, "lost_or_stolen", idempotency_key=_key())

        assert await _fetch_product_status(_OWN_DEBIT_CARD_ID) == original_status

    asyncio.run(_run())


def test_idempotency_key_replay(it_env: None, restore_cards: set[str]) -> None:
    restore_cards.add(_OWN_CARD_ID)
    writes = PostgresBankWrites(_ctx(_OWN_CUSTOMER_ID))
    lock_key = _key()
    block_key = _key()
    replacement_key = _key()

    async def _run() -> None:
        first_lock = await writes.lock_card(_OWN_CARD_ID, idempotency_key=lock_key)
        second_lock = await writes.lock_card(_OWN_CARD_ID, idempotency_key=lock_key)
        assert first_lock.readback == second_lock.readback

        first_block = await writes.block_card(
            _OWN_CARD_ID, "lost_or_stolen", idempotency_key=block_key
        )
        second_block = await writes.block_card(
            _OWN_CARD_ID, "lost_or_stolen", idempotency_key=block_key
        )
        assert first_block.readback == second_block.readback

        first_replacement = await writes.order_replacement(
            _OWN_CARD_ID, "on_file", idempotency_key=replacement_key
        )
        second_replacement = await writes.order_replacement(
            _OWN_CARD_ID, "on_file", idempotency_key=replacement_key
        )
        assert first_replacement.readback == second_replacement.readback
        assert first_replacement.tracking_id == second_replacement.tracking_id

        assert await _table_count("app.card_status_history", _OWN_CARD_ID) == 1
        assert await _table_count("app.card_replacements", _OWN_CARD_ID) == 1

    asyncio.run(_run())
