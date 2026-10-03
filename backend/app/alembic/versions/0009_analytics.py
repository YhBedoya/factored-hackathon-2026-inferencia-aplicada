"""Analytics schema, worker state, messages index and the worker role.

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-02

Spec `interaction-analytics-pipeline.md` "Contracts" -> "Schema `analytics`";
D7, D8, D22.

`analytics.interactions` holds one row per finished interaction and
`analytics.interaction_intents` one row per intent occurrence. Neither has a
foreign key to `app.conversations` (mock rows have no conversation) and neither
holds message text or a customer identifier. The worker runs as its own role,
`analytics_worker`: read-only on `app`/`audit`/`bank`, read-write on
`analytics`, plus `INSERT` on `audit.llm_calls` for the sentiment ledger row.
Roles are cluster-wide while this migration runs once per database, so the
role creation is idempotent and the password never appears in the file.
"""

import sqlalchemy as sa
from alembic import op

from app.core.config import get_settings

# revision identifiers, used by Alembic.
revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | None = None
depends_on: str | None = None

_ROLE = "analytics_worker"
_SENTIMENT = "('negative','neutral','positive')"


def _int(name: str) -> sa.Column:
    return sa.Column(name, sa.Integer(), nullable=False, server_default="0")


def _flag(name: str) -> sa.Column:
    return sa.Column(name, sa.Boolean(), nullable=False, server_default=sa.false())


def _money(name: str, *, nullable: bool = False) -> sa.Column:
    return sa.Column(
        name,
        sa.Numeric(12, 6),
        nullable=nullable,
        server_default=None if nullable else "0",
    )


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS analytics")

    op.create_table(
        "interactions",
        sa.Column("conversation_id", sa.Uuid(), primary_key=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_reason", sa.Text(), nullable=False),
        sa.Column("duration_s", sa.Integer(), nullable=False),
        sa.Column("language", sa.Text(), nullable=True),
        sa.Column("country", sa.Text(), nullable=True),
        sa.Column("channel", sa.Text(), nullable=True),
        _int("customer_messages"),
        _int("bot_messages"),
        _int("agent_messages"),
        _int("turns"),
        _int("real_intent_count"),
        sa.Column("resolved", sa.Boolean(), nullable=True),
        _flag("abandoned"),
        _flag("abstained"),
        _flag("degraded"),
        _flag("escalated"),
        _int("handoff_count"),
        sa.Column("handoff_queue", sa.Text(), nullable=True),
        sa.Column("handoff_reason", sa.Text(), nullable=True),
        sa.Column("handoff_cause_group", sa.Text(), nullable=True),
        sa.Column("time_to_claim_s", sa.Integer(), nullable=True),
        _money("cost_usd"),
        _money("cost_nlu_usd"),
        _money("cost_compose_usd"),
        _money("cost_handoff_summary_usd"),
        _int("llm_call_count"),
        sa.Column("sentiment_overall", sa.Text(), nullable=True),
        sa.Column("sentiment_start", sa.Text(), nullable=True),
        sa.Column("sentiment_end", sa.Text(), nullable=True),
        sa.Column("sentiment_model", sa.Text(), nullable=True),
        sa.Column("sentiment_prompt_version", sa.Text(), nullable=True),
        _money("sentiment_cost_usd", nullable=True),
        sa.Column("sentiment_scored_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("metrics_version", sa.Integer(), nullable=False),
        sa.CheckConstraint("source IN ('real','mock')", name="ck_interactions_source"),
        sa.CheckConstraint(
            "end_reason IN ('customer_closed','idle','handoff_returned')",
            name="ck_interactions_end_reason",
        ),
        sa.CheckConstraint(
            f"(sentiment_overall IS NULL OR sentiment_overall IN {_SENTIMENT})"
            f" AND (sentiment_start IS NULL OR sentiment_start IN {_SENTIMENT})"
            f" AND (sentiment_end IS NULL OR sentiment_end IN {_SENTIMENT})",
            name="ck_interactions_sentiment",
        ),
        schema="analytics",
    )
    op.create_index("ix_interactions_ended_at", "interactions", ["ended_at"], schema="analytics")

    op.create_table(
        "interaction_intents",
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("intent", sa.Text(), nullable=False),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("needed_clarification", sa.Boolean(), nullable=False),
        sa.Column("turns", sa.Integer(), nullable=False),
        sa.Column("bot_offered", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.PrimaryKeyConstraint("conversation_id", "seq"),
        sa.CheckConstraint(
            "outcome IN ('resolved','handoff','abstained','abandoned','cancelled')",
            name="ck_interaction_intents_outcome",
        ),
        schema="analytics",
    )

    op.create_table(
        "worker_state",
        sa.Column("id", sa.SmallInteger(), primary_key=True),
        sa.Column("watermark", sa.DateTime(timezone=True), nullable=True),
        sa.Column("mock_seeded_through", sa.Date(), nullable=True),
        sa.CheckConstraint("id = 1", name="ck_worker_state_single_row"),
        schema="analytics",
    )
    op.execute("INSERT INTO analytics.worker_state (id) VALUES (1)")

    # D7: the candidate lookup scans messages by time, not every conversation.
    op.create_index("ix_messages_created_at", "messages", ["created_at"], schema="app")

    # Human decision at the gate: `closed_at` is also a candidate source.
    op.create_index("ix_conversations_closed_at", "conversations", ["closed_at"], schema="app")

    # The candidate query filters handoffs on each of these; 0005's index leads with `status`.
    for column in ("created_at", "claimed_at", "returned_at"):
        op.create_index(f"ix_handoffs_{column}", "handoffs", [column], schema="app")

    _create_role_and_grants()


def _create_role_and_grants() -> None:
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{_ROLE}') THEN
                CREATE ROLE {_ROLE} LOGIN;
            END IF;
        END
        $$
        """
    )
    # D8 (P4): an empty password leaves the role as it is. The literal is
    # quoted by the database and never reaches the file or any output.
    password = get_settings().analytics_db_password
    if password:
        bind = op.get_bind()
        stmt = bind.execute(
            sa.text("SELECT format('ALTER ROLE analytics_worker PASSWORD %L', CAST(:pw AS text))"),
            {"pw": password},
        ).scalar_one()
        bind.execute(sa.text(stmt.replace(":", r"\:")))

    for schema in ("app", "audit", "bank", "analytics"):
        op.execute(f"GRANT USAGE ON SCHEMA {schema} TO {_ROLE}")
    for schema in ("app", "audit", "bank"):
        op.execute(f"GRANT SELECT ON ALL TABLES IN SCHEMA {schema} TO {_ROLE}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA analytics TO {_ROLE}")
    op.execute(f"GRANT INSERT ON audit.llm_calls TO {_ROLE}")


def downgrade() -> None:
    # Dropping the schema drops the `analytics` grants with it. The role stays
    # (cluster-wide, other databases may still use it).
    op.execute(f"REVOKE INSERT ON audit.llm_calls FROM {_ROLE}")
    for schema in ("app", "audit", "bank"):
        op.execute(f"REVOKE SELECT ON ALL TABLES IN SCHEMA {schema} FROM {_ROLE}")
    for schema in ("app", "audit", "bank", "analytics"):
        op.execute(f"REVOKE USAGE ON SCHEMA {schema} FROM {_ROLE}")

    for column in ("returned_at", "claimed_at", "created_at"):
        op.drop_index(f"ix_handoffs_{column}", table_name="handoffs", schema="app")
    op.drop_index("ix_conversations_closed_at", table_name="conversations", schema="app")
    op.drop_index("ix_messages_created_at", table_name="messages", schema="app")
    op.drop_index("ix_interactions_ended_at", table_name="interactions", schema="analytics")
    op.drop_table("worker_state", schema="analytics")
    op.drop_table("interaction_intents", schema="analytics")
    op.drop_table("interactions", schema="analytics")
    op.execute("DROP SCHEMA analytics")
