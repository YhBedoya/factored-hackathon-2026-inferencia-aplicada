"""Allow a NULL temperature on `audit.llm_calls`.

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-29

`claude-sonnet-5-5` (the `nlu` step) rejects any `temperature`, so the step
sends none and the ledger records NULL for it.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.alter_column(
        "llm_calls", "temperature", existing_type=sa.Numeric(), nullable=True, schema="audit"
    )


def downgrade() -> None:
    # Rows written without a temperature have no honest value; 0 is the pre-0008 default.
    op.execute("UPDATE audit.llm_calls SET temperature = 0 WHERE temperature IS NULL")
    op.alter_column(
        "llm_calls", "temperature", existing_type=sa.Numeric(), nullable=False, schema="audit"
    )
