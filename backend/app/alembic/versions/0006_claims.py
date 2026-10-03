"""Claim idempotency on `bank.complaints`.

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-28

Spec `d4-b-disputes-handoff-screens.md` "Contracts" -> "Migration
`0005_claims_staff`"; D14, D15, D23. Renumbered to `0006` when D4-A's
`0005_handoffs_staff` landed first, and reduced to the claim columns: the
staff-account shape of `identity.accounts` (nullable `customer_id`,
`username`, `display_name`) is D4-A's `0005`.

`bank.complaints` gains `transaction_id` (which transaction a claim row
covers) and a nullable, unique `idempotency_key`: the per-row key is
`<token_id>:<step_index>:<tx_id>` (D15), so a replayed step re-reads the
existing rows instead of writing a second set (D3-A D11 pattern, R12). Both
columns are nullable because every pre-existing complaint row (and every
non-claim row written later) has neither.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | None = None
depends_on: str | None = None


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


def downgrade() -> None:
    op.drop_constraint("uq_complaints_idempotency_key", "complaints", schema="bank", type_="unique")
    op.drop_column("complaints", "idempotency_key", schema="bank")
    op.drop_column("complaints", "transaction_id", schema="bank")
