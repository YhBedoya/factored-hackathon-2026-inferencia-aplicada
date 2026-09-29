"""Hosts the compiled turn graph across the app's lifetime (D16).

`open_host` builds the checkpointer's connection pool once per process, runs
`AsyncPostgresSaver.setup()` (idempotent -- creates the `langgraph` schema's
tables on first boot, no-ops after that), and compiles the graph over it.
`close_host` cancels any turn tasks still running -- D16's "a restart loses
nothing" means a restart *between* turns; a turn in flight when the process
dies is not resumed -- then closes the pool.

`psycopg_conninfo` only strips the `+asyncpg` driver suffix `DATABASE_URL`
carries for SQLAlchemy: same database, same host, a plain psycopg3 DSN.
"""

import asyncio
import contextlib
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, get_args

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph.state import CompiledStateGraph
from psycopg import AsyncConnection
from psycopg.rows import DictRow, dict_row
from psycopg_pool import AsyncConnectionPool
from pydantic import BaseModel

from app.core.actions import ActionResult
from app.core.llm import LLMClient
from app.domains.conversation.graph import (
    ConfirmationDecision,
    GraphState,
    TurnInput,
    TurnOutput,
    build_graph,
)
from app.domains.conversation.schemas import NLUResult
from app.domains.conversation.state import Fact
from app.domains.conversation.ui import UIEvent
from app.domains.handoff.schemas import HandoffEvidence

__all__ = ["TurnHost", "close_host", "open_host", "psycopg_conninfo"]


def _models_in(annotation: object, seen: set[type]) -> None:
    """Collect every Pydantic model and enum reachable from `annotation`."""
    if isinstance(annotation, type) and issubclass(annotation, (BaseModel, Enum)):
        if annotation in seen:
            return
        seen.add(annotation)
        if issubclass(annotation, BaseModel):
            for info in annotation.model_fields.values():
                _models_in(info.annotation, seen)
        return
    for arg in get_args(annotation):
        _models_in(arg, seen)


def _checkpoint_types() -> tuple[type, ...]:
    seen: set[type] = set()
    for root in (
        *get_args(get_args(UIEvent)[0]),
        ActionResult,
        ConfirmationDecision,
        Fact,
        *(HandoffEvidence, NLUResult),
    ):
        _models_in(root, seen)
    return tuple(sorted(seen, key=lambda t: (t.__module__, t.__qualname__)))


# Every Pydantic model (and enum) the graph writes into checkpointed state:
# the `UIEvent` union, `NLUResult`, `Fact`, `ActionResult`, `HandoffEvidence`,
# `ConfirmationDecision`, plus whatever they nest. The msgpack serde is strict
# (`allowed_msgpack_modules` is a set, not `True`), so an unlisted type would
# come back as a raw dict and break a flow silently. Derived from the models
# themselves so a new UI event or nested field is covered without editing this.
CHECKPOINT_TYPES: tuple[type, ...] = _checkpoint_types()


def checkpoint_serde() -> JsonPlusSerializer:
    """The checkpointer's serde, allowing exactly `CHECKPOINT_TYPES`."""
    return JsonPlusSerializer(
        allowed_msgpack_modules=[(t.__module__, t.__qualname__) for t in CHECKPOINT_TYPES]
    )


def psycopg_conninfo(database_url: str) -> str:
    """`DATABASE_URL` (`postgresql+asyncpg://...`) -> a plain psycopg3 conninfo."""
    return database_url.replace("postgresql+asyncpg://", "postgresql://")


@dataclass
class TurnHost:
    """Everything one process needs to run turns (D16): the compiled graph,
    the checkpointer's connection pool, the shared `LLMClient`, and the
    in-flight turn tasks `close_host` cancels at shutdown.
    """

    graph: CompiledStateGraph[GraphState, Any, TurnInput, TurnOutput]
    pool: AsyncConnectionPool[AsyncConnection[DictRow]]
    llm: LLMClient
    tasks: set[asyncio.Task[None]] = field(default_factory=set)


async def open_host(database_url: str, llm: LLMClient) -> TurnHost:
    """Open the checkpointer pool, run its one-time `setup()`, and compile
    the graph over it (D16). `search_path=langgraph` keeps the checkpoint
    tables out of `public` (migration `0002`'s `CREATE SCHEMA IF NOT EXISTS
    langgraph`).
    """
    pool: AsyncConnectionPool[AsyncConnection[DictRow]] = AsyncConnectionPool(
        psycopg_conninfo(database_url),
        open=False,
        kwargs={
            "autocommit": True,
            "prepare_threshold": 0,
            "row_factory": dict_row,
            "options": "-c search_path=langgraph",
        },
    )
    await pool.open()
    saver = AsyncPostgresSaver(pool, serde=checkpoint_serde())
    await saver.setup()
    graph = build_graph(saver)
    return TurnHost(graph=graph, pool=pool, llm=llm)


async def close_host(host: TurnHost) -> None:
    """Cancel any turn tasks still running, await them, then close the pool
    (D16). Cancellation is expected to raise `CancelledError` back into each
    task; that is the shutdown path working, not a failure to report.
    """
    for task in list(host.tasks):
        task.cancel()
    for task in list(host.tasks):
        with contextlib.suppress(asyncio.CancelledError):
            await task
    await host.pool.close()
