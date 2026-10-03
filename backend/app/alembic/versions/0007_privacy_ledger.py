"""PII vault and the per-attempt LLM-call ledger.

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-29

Spec `d5-a-privacy-grounding-eval.md` "Contracts" -> "Migration
`0007_privacy_ledger`"; D5-D9.

`app.pii_vault` maps a per-conversation token to its Fernet-encrypted raw
value. `audit.llm_calls` is the append-only ledger of every LLM attempt
(including refused ones, whose `input_text` is NULL). `app.messages` needs no
column change.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "pii_vault",
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("token", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("value_enc", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("conversation_id", "token"),
        schema="app",
    )
    op.create_table(
        "llm_calls",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=True),
        sa.Column("turn_id", sa.Uuid(), nullable=True),
        sa.Column("step", sa.Text(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("model_id", sa.Text(), nullable=False),
        sa.Column("prompt_version", sa.Text(), nullable=False),
        sa.Column("temperature", sa.Numeric(), nullable=False),
        sa.Column("attempt", sa.SmallInteger(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("input_text", sa.Text(), nullable=True),
        sa.Column("output_json", postgresql.JSONB(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("cost_usd", sa.Numeric(12, 6), nullable=True),
        sa.Column("latency_ms", sa.Numeric(), nullable=False),
        sa.Column("langfuse_trace_id", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "status IN ('ok','invalid','unavailable','refused')",
            name="ck_llm_calls_status",
        ),
        schema="audit",
    )
    op.create_index(
        "ix_llm_calls_conversation_id_at",
        "llm_calls",
        ["conversation_id", "at"],
        schema="audit",
    )


def downgrade() -> None:
    op.drop_index("ix_llm_calls_conversation_id_at", table_name="llm_calls", schema="audit")
    op.drop_table("llm_calls", schema="audit")
    op.drop_table("pii_vault", schema="app")
