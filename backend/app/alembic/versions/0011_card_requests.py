"""Card open/close requests and the customer profile change history.

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-04

Spec `d9-c-card-requests.md` "Contracts" -> 4. `bank.products` gains the
app-origin columns (`03` §6) so a card opened by the app is told apart from the
dataset. `app.card_requests` is the one row per request that staff decide; the
two partial unique indexes allow one pending open per customer and one pending
close per card. `app.customer_profile_history` keeps old/new values Fernet
encrypted (R5), so it stores ciphertext only.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "products",
        sa.Column("origin", sa.Text(), nullable=False, server_default="dataset"),
        schema="bank",
    )
    op.add_column(
        "products",
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        schema="bank",
    )
    op.add_column("products", sa.Column("conversation_id", sa.Uuid(), nullable=True), schema="bank")

    op.create_table(
        "card_requests",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("reference", sa.Text(), nullable=False),
        sa.Column("customer_id", sa.Text(), nullable=False),
        sa.Column(
            "conversation_id",
            sa.Uuid(),
            sa.ForeignKey("app.conversations.id"),
            nullable=False,
        ),
        sa.Column("handoff_id", sa.Uuid(), sa.ForeignKey("app.handoffs.id"), nullable=True),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("card_kind", sa.Text(), nullable=False),
        sa.Column("product_id", sa.Text(), nullable=True),
        sa.Column("reason_code", sa.Text(), nullable=True),
        sa.Column(
            "changed_fields",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("decision", sa.Text(), nullable=True),
        sa.Column("decline_reason", sa.Text(), nullable=True),
        sa.Column("credit_limit", sa.Numeric(), nullable=True),
        sa.Column(
            "agent_id",
            sa.Uuid(),
            sa.ForeignKey("identity.accounts.account_id"),
            nullable=True,
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("idempotency_key", sa.Text(), nullable=True),
        sa.Column("decision_key", sa.Text(), nullable=True),
        sa.UniqueConstraint("reference", name="uq_card_requests_reference"),
        sa.UniqueConstraint("idempotency_key", name="uq_card_requests_idempotency_key"),
        sa.UniqueConstraint("decision_key", name="uq_card_requests_decision_key"),
        sa.CheckConstraint("kind IN ('open','close')", name="ck_card_requests_kind"),
        sa.CheckConstraint("card_kind IN ('credit','debit')", name="ck_card_requests_card_kind"),
        sa.CheckConstraint("status IN ('pending','decided')", name="ck_card_requests_status"),
        sa.CheckConstraint(
            "decision IS NULL OR decision IN "
            "('approve','decline','cancel','keep','not_cancelled_balance')",
            name="ck_card_requests_decision",
        ),
        schema="app",
    )
    op.create_index(
        "uq_card_requests_pending_open_customer",
        "card_requests",
        ["customer_id"],
        unique=True,
        schema="app",
        postgresql_where=sa.text("kind = 'open' AND status = 'pending'"),
    )
    op.create_index(
        "uq_card_requests_pending_close_product",
        "card_requests",
        ["product_id"],
        unique=True,
        schema="app",
        postgresql_where=sa.text("kind = 'close' AND status = 'pending'"),
    )

    op.create_table(
        "customer_profile_history",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("customer_id", sa.Text(), nullable=False),
        sa.Column("field", sa.Text(), nullable=False),
        sa.Column("old_value_enc", sa.Text(), nullable=True),
        sa.Column("new_value_enc", sa.Text(), nullable=False),
        sa.Column("actor", sa.Text(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=True),
        sa.Column(
            "card_request_id", sa.Uuid(), sa.ForeignKey("app.card_requests.id"), nullable=True
        ),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "field IN ('email','mobile_phone','address','occupation','estimated_monthly_income')",
            name="ck_customer_profile_history_field",
        ),
        schema="app",
    )
    op.create_index(
        "ix_customer_profile_history_customer_at",
        "customer_profile_history",
        ["customer_id", sa.text("at DESC")],
        schema="app",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_customer_profile_history_customer_at",
        table_name="customer_profile_history",
        schema="app",
    )
    op.drop_table("customer_profile_history", schema="app")
    op.drop_index(
        "uq_card_requests_pending_close_product", table_name="card_requests", schema="app"
    )
    op.drop_index(
        "uq_card_requests_pending_open_customer", table_name="card_requests", schema="app"
    )
    op.drop_table("card_requests", schema="app")
    op.drop_column("products", "conversation_id", schema="bank")
    op.drop_column("products", "created_at", schema="bank")
    op.drop_column("products", "origin", schema="bank")
