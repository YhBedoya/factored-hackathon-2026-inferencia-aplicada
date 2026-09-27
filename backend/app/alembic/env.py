"""Alembic environment: async engine, URL from settings, no drift on bank.*.

`app.core.config.get_settings().database_url` is the single source of truth
for the connection, so a local `alembic upgrade head` and the app's own
engine never point at different databases (the caller can still override
`DATABASE_URL` in the environment, e.g. to point at `latam_golden`).

`target_metadata` is `SQLModel.metadata`. It holds no tables today: D4 keeps
`bank.*` DDL as a hand-written migration with no ORM classes, so there is
nothing for autogenerate to compare against. `include_object` tells
autogenerate to skip every reflected `bank.*` table and `app.system_metadata`
(both owned by this hand-written migration, not by a model), so `alembic
check` reports no drift even though those tables exist in the database.
"""

import asyncio
from logging.config import fileConfig
from typing import Literal

from alembic import context
from sqlalchemy import Connection, Table, pool
from sqlalchemy.ext.asyncio import async_engine_from_config
from sqlalchemy.schema import SchemaItem
from sqlmodel import SQLModel

from app.core.config import get_settings

_ObjectType = Literal[
    "schema",
    "table",
    "column",
    "index",
    "unique_constraint",
    "foreign_key_constraint",
    "check_constraint",
]

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = SQLModel.metadata

config.set_main_option("sqlalchemy.url", get_settings().database_url)


def include_object(
    object_: SchemaItem,
    name: str | None,
    type_: _ObjectType,
    reflected: bool,
    compare_to: SchemaItem | None,
) -> bool:
    """Skip reflected `bank.*` tables and `app.system_metadata`.

    `reflected and compare_to is None` means autogenerate found the table in
    the database but has no metadata to compare it to, which is exactly the
    case for the hand-written tables. Without this, every `alembic check` or
    `revision --autogenerate` would propose dropping them.
    """
    if type_ == "table" and reflected and compare_to is None and isinstance(object_, Table):
        if object_.schema == "bank":
            return False
        if object_.schema == "app" and name == "system_metadata":
            return False
    return True


def run_migrations_offline() -> None:
    """Run migrations without a live DB connection, emitting SQL only."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_schemas=True,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_schemas=True,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Run migrations against a live DB, through an async engine (asyncpg)."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
