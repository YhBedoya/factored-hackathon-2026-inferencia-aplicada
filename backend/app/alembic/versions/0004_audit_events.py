"""`audit.audit_events`, the append-only trail for every guarded decision.

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-28

Spec `d3-a-guardrails-write-path.md` "Contracts" -> "Migration `0004`"; D12,
D13. `AuditRecorder` inserts one row per event and never updates or deletes
one, so the table needs no history side-table of its own. `payload` is
structural only (no user text, R5) and is `not null`; `sources` defaults to
an empty JSON array for events that don't cite a policy/table source.
`policy_version` is the combined policy hash (D2) and is required on every
row. UUID PK is generated in code, matching 0002/0003.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("conversation_id", sa.Uuid(), nullable=True),
        sa.Column("turn_id", sa.Uuid(), nullable=True),
        sa.Column("actor", sa.Text(), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("sources", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("policy_version", sa.Text(), nullable=False),
        sa.Column("model", postgresql.JSONB(), nullable=True),
        sa.Column("trace_id", sa.Text(), nullable=True),
        sa.Column("langfuse_trace_id", sa.Text(), nullable=True),
        schema="audit",
    )
    op.create_index(
        "ix_audit_events_conversation_id_at",
        "audit_events",
        ["conversation_id", "at"],
        schema="audit",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_audit_events_conversation_id_at",
        table_name="audit_events",
        schema="audit",
    )
    op.drop_table("audit_events", schema="audit")
