"""Staff accounts on `identity.accounts` and the `app.handoffs` queue.

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-28

Spec `d4-a-escalation-handoff-deploy.md` "Contracts" -> "Migration
`0005_handoffs_staff`". Staff rows (`agent`/`admin`) have no bank customer, so
`customer_id` becomes nullable; the second CHECK keeps that honest (only
customers carry one). Staff `login_key` is filled by the seed, so the existing
NOT NULL unique constraint still holds. The partial unique index on
`app.handoffs` allows one open handoff per conversation.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.alter_column("accounts", "customer_id", nullable=True, schema="identity")
    op.add_column("accounts", sa.Column("username", sa.Text(), nullable=True), schema="identity")
    op.add_column(
        "accounts", sa.Column("display_name", sa.Text(), nullable=True), schema="identity"
    )
    op.add_column("accounts", sa.Column("staff_queue", sa.Text(), nullable=True), schema="identity")
    op.create_unique_constraint("uq_accounts_username", "accounts", ["username"], schema="identity")
    op.create_check_constraint(
        "ck_accounts_role",
        "accounts",
        "role IN ('customer','agent','admin')",
        schema="identity",
    )
    op.create_check_constraint(
        "ck_accounts_customer_id_role",
        "accounts",
        "(role = 'customer') = (customer_id IS NOT NULL)",
        schema="identity",
    )

    op.create_table(
        "handoffs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "conversation_id",
            sa.Uuid(),
            sa.ForeignKey("app.conversations.id"),
            nullable=False,
        ),
        sa.Column("queue", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("priority", sa.Text(), nullable=False),
        sa.Column("packet", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="queued"),
        sa.Column(
            "agent_id",
            sa.Uuid(),
            sa.ForeignKey("identity.accounts.account_id"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("returned_at", sa.DateTime(timezone=True), nullable=True),
        schema="app",
    )
    op.create_index(
        "ix_handoffs_status_queue_created_at",
        "handoffs",
        ["status", "queue", sa.text("created_at DESC")],
        schema="app",
    )
    op.create_index(
        "uq_handoffs_open_conversation",
        "handoffs",
        ["conversation_id"],
        unique=True,
        schema="app",
        postgresql_where=sa.text("status IN ('queued','claimed')"),
    )


def downgrade() -> None:
    op.drop_index("uq_handoffs_open_conversation", table_name="handoffs", schema="app")
    op.drop_index("ix_handoffs_status_queue_created_at", table_name="handoffs", schema="app")
    op.drop_table("handoffs", schema="app")

    op.drop_constraint("ck_accounts_customer_id_role", "accounts", schema="identity")
    op.drop_constraint("ck_accounts_role", "accounts", schema="identity")
    op.drop_constraint("uq_accounts_username", "accounts", schema="identity")
    op.drop_column("accounts", "staff_queue", schema="identity")
    op.drop_column("accounts", "display_name", schema="identity")
    op.drop_column("accounts", "username", schema="identity")
    op.alter_column("accounts", "customer_id", nullable=False, schema="identity")
