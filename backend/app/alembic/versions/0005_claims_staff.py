"""Claim idempotency on `bank.complaints`, and the staff account shape on
`identity.accounts`.

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-28

Spec `d4-b-disputes-handoff-screens.md` "Contracts" -> "Migration
`0005_claims_staff`"; D3, D4, D14, D15, D23. B's migration; A's `app.handoffs`
migration is `0006` (down `0005`, D23), so this one must stay `0005`.

`bank.complaints` gains `transaction_id` (which transaction a claim row
covers) and a nullable, unique `idempotency_key`: the per-row key is
`<token_id>:<step_index>:<tx_id>` (D15), so a replayed step re-reads the
existing rows instead of writing a second set (D3-A D11 pattern, R12). Both
columns are nullable because every pre-existing complaint row (and every
non-claim row written later) has neither.

`identity.accounts` grows a `role='agent'` shape: `customer_id` drops its
NOT NULL (a staff row has none), and the table gains `username` (the staff
login key input, unique) and `display_name` (shown in the `mode` event, D13).
The CHECK keeps the two roles mutually exclusive and internally consistent:
a customer row must carry `customer_id` and no dependency on `username`; an
agent row must carry `username` and no `customer_id`. `downgrade()` deletes
every `role='agent'` row before restoring `customer_id NOT NULL`, since an
agent row (customer_id IS NULL) would violate it otherwise.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | None = None
depends_on: str | None = None

_ACCOUNTS_ROLE_CHECK = (
    "(role='customer' AND customer_id IS NOT NULL) "
    "OR (role='agent' AND customer_id IS NULL AND username IS NOT NULL)"
)


def upgrade() -> None:
    op.add_column(
        "complaints",
        sa.Column("transaction_id", sa.Text(), nullable=True),
        schema="bank",
    )
    op.add_column(
        "complaints",
        sa.Column("idempotency_key", sa.Text(), nullable=True),
        schema="bank",
    )
    op.create_unique_constraint(
        "uq_complaints_idempotency_key",
        "complaints",
        ["idempotency_key"],
        schema="bank",
    )

    op.alter_column(
        "accounts",
        "customer_id",
        nullable=True,
        schema="identity",
    )
    op.add_column(
        "accounts",
        sa.Column("username", sa.Text(), nullable=True),
        schema="identity",
    )
    op.add_column(
        "accounts",
        sa.Column("display_name", sa.Text(), nullable=True),
        schema="identity",
    )
    op.create_unique_constraint(
        "uq_accounts_username",
        "accounts",
        ["username"],
        schema="identity",
    )
    op.create_check_constraint(
        "ck_accounts_role_customer_id",
        "accounts",
        _ACCOUNTS_ROLE_CHECK,
        schema="identity",
    )


def downgrade() -> None:
    op.drop_constraint("ck_accounts_role_customer_id", "accounts", schema="identity", type_="check")
    op.drop_constraint("uq_accounts_username", "accounts", schema="identity", type_="unique")

    # An agent row has `customer_id IS NULL`, which would violate the NOT
    # NULL restored below, so every staff account is removed first.
    op.execute("DELETE FROM identity.accounts WHERE role = 'agent'")

    op.drop_column("accounts", "display_name", schema="identity")
    op.drop_column("accounts", "username", schema="identity")
    op.alter_column(
        "accounts",
        "customer_id",
        nullable=False,
        schema="identity",
    )

    op.drop_constraint("uq_complaints_idempotency_key", "complaints", schema="bank", type_="unique")
    op.drop_column("complaints", "idempotency_key", schema="bank")
    op.drop_column("complaints", "transaction_id", schema="bank")
