"""`app.card_controls`, `app.card_status_history` and `app.card_replacements`.

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-28

Spec `d3-a-guardrails-write-path.md` "Contracts" -> "Migration `0003`"; D9,
D10, D11. These three tables are the raw-write targets `cards.service`
writes through inside the same transaction as the `bank.products` update
they accompany (R12), so `block_card` can insert a `card_status_history`
row and flip `bank.products.product_status` atomically.

None of the three carries a FK to `app.conversations`: `conversation_id`
here is a plain business key the same way it is on `app.conversations`
itself (02, following the same reasoning as 0002's docstring), and none of
them stores a raw postal address -- `card_replacements` keeps only
`address_ref` (an opaque vault reference) and `address_changed`; the
encrypted snapshot arrives with D5-A1. Each table's `idempotency_key` is
unique but nullable (D11): a raw write that races or replays with the same
key re-reads the existing row instead of writing a second one, so `null`
stays available for any row written outside that path. UUID PKs are
generated in code, so `id`/`product_id` have no server-side default,
matching 0002.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "card_controls",
        sa.Column("product_id", sa.Text(), primary_key=True),
        sa.Column("locked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("locked_by", sa.Text(), nullable=True),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("idempotency_key", sa.Text(), nullable=True, unique=True),
        schema="app",
    )

    op.create_table(
        "card_status_history",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("product_id", sa.Text(), nullable=False),
        sa.Column("old_status", sa.Text(), nullable=True),
        sa.Column("new_status", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("actor", sa.Text(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=True),
        sa.Column("trace_id", sa.Text(), nullable=True),
        sa.Column(
            "at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("idempotency_key", sa.Text(), nullable=True, unique=True),
        schema="app",
    )
    op.create_index(
        "ix_card_status_history_product_id_at",
        "card_status_history",
        ["product_id", sa.text("at DESC")],
        schema="app",
    )

    op.create_table(
        "card_replacements",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("product_id", sa.Text(), nullable=False),
        sa.Column("address_ref", sa.Text(), nullable=False),
        sa.Column("address_changed", sa.Boolean(), nullable=False),
        sa.Column("tracking_id", sa.Text(), nullable=False, unique=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("idempotency_key", sa.Text(), nullable=True, unique=True),
        schema="app",
    )


def downgrade() -> None:
    op.drop_table("card_replacements", schema="app")

    op.drop_index(
        "ix_card_status_history_product_id_at",
        table_name="card_status_history",
        schema="app",
    )
    op.drop_table("card_status_history", schema="app")

    op.drop_table("card_controls", schema="app")
