"""Agent cost and the serving path on analytics interactions.

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-03

Spec `cardy-agent-s1-conversation-reads-block.md` D24: `cost_agent_usd` is the
agent step's LLM cost and `served_by` says which path wrote the replies
(`agent`, `pipeline` or `mixed`). The defaults make existing and mock rows read
as `pipeline` with no agent cost.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "interactions",
        sa.Column("cost_agent_usd", sa.Numeric(12, 6), nullable=False, server_default="0"),
        schema="analytics",
    )
    op.add_column(
        "interactions",
        sa.Column("served_by", sa.Text(), nullable=False, server_default="pipeline"),
        schema="analytics",
    )


def downgrade() -> None:
    op.drop_column("interactions", "served_by", schema="analytics")
    op.drop_column("interactions", "cost_agent_usd", schema="analytics")
