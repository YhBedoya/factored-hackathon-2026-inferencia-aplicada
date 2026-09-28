"""Identity, conversations, messages and the `langgraph` schema.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-27

Spec `d2-a-login-read-tools-api.md` "Contracts" -> "Migration `0002`"; `03`
§6 (Alembic owns the DDL for every schema, and the LangGraph checkpointer
manages its own tables inside `langgraph` once its `setup()` runs -- this
migration only creates the empty schema for it to populate).

`identity.accounts` is customer-only for this card: no staff columns and no
`staff_users` table (those arrive with the future staff-panel card).
`app.conversations` carries `customer_id` as a plain business key with no FK
(it never becomes a joinable table for anything but the conversation
domain), and it, `app.messages`, `identity.accounts` and
`identity.revoked_tokens` get UUID/text primary keys generated in code, so
none of them have a server-side PK default.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "accounts",
        sa.Column("account_id", sa.Uuid(), primary_key=True),
        sa.Column("role", sa.Text(), nullable=False, server_default="customer"),
        sa.Column(
            "customer_id",
            sa.Text(),
            sa.ForeignKey("bank.customers.customer_id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("login_key", sa.Text(), nullable=False, unique=True),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default="active"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        schema="identity",
    )

    op.create_table(
        "revoked_tokens",
        sa.Column("jti", sa.Text(), primary_key=True),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        schema="identity",
    )

    op.create_table(
        "conversations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("customer_id", sa.Text(), nullable=False),
        sa.Column("channel", sa.Text(), server_default="web"),
        sa.Column("language", sa.Text()),
        sa.Column("mode", sa.Text(), server_default="bot"),
        sa.Column("status", sa.Text(), server_default="open"),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
        schema="app",
    )
    op.create_index(
        "ix_conversations_customer_id",
        "conversations",
        ["customer_id"],
        schema="app",
    )

    op.create_table(
        "messages",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "conversation_id",
            sa.Uuid(),
            sa.ForeignKey("app.conversations.id", ondelete="CASCADE"),
        ),
        sa.Column("turn_id", sa.Uuid()),
        sa.Column("role", sa.Text()),
        sa.Column("content", sa.Text()),
        sa.Column("content_masked", sa.Text(), nullable=True),
        sa.Column("ui_payload", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        schema="app",
    )
    op.create_index(
        "ix_messages_conversation_id_created_at",
        "messages",
        ["conversation_id", "created_at"],
        schema="app",
    )

    op.execute("CREATE SCHEMA IF NOT EXISTS langgraph")
    # The Postgres checkpointer's own `setup()` (called from the app's
    # lifespan) creates and migrates its tables inside this schema; Alembic
    # only owns the schema shell (03 §3).


def downgrade() -> None:
    op.drop_index("ix_messages_conversation_id_created_at", table_name="messages", schema="app")
    op.drop_table("messages", schema="app")

    op.drop_index("ix_conversations_customer_id", table_name="conversations", schema="app")
    op.drop_table("conversations", schema="app")

    op.drop_table("revoked_tokens", schema="identity")

    op.drop_table("accounts", schema="identity")

    op.execute("DROP SCHEMA IF EXISTS langgraph CASCADE")
