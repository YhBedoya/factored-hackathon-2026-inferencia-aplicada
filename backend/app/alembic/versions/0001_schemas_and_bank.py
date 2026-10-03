"""Schemas (bank, app, identity, audit), the 13 bank.* tables, app.system_metadata.

Revision ID: 0001
Revises:
Create Date: 2026-09-26

`bank.*` is hand-written, not reflected from SQLModel classes (D4): the 13
tables carry the source CSV columns verbatim, in source order, with no hive
partition columns and no FK constraints (03 §3 keeps orphaned rows visible
instead of hiding them). PKs are the first `*_id` column, except
`daily_exchange_rates`, whose natural key is a triple. `complaints` is the
only table the app appends to today, so it alone gets `origin`, `created_at`
and `conversation_id` (D13; `digital_events` stays proposed).

Column types follow the shared typing rule (see the card's state file):
ids/codes/free text -> text, DATE -> date, TIME -> time (never shifted),
TIMESTAMP -> timestamptz read as UTC (D1), the listed money columns plus
`interest_rate`/`fraud_score` -> numeric, `days_past_due` -> integer,
`True`/`False` -> boolean, other integer-valued counts -> integer, and every
other fractional value (scores, lat/long, durations) -> double precision.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None

_SCHEMAS = ("bank", "app", "identity", "audit")

# Tables dropped in reverse dependency-free order (no FKs, so any order is
# safe; this mirrors creation order for readability).
_BANK_TABLES = (
    "branches",
    "customers",
    "daily_exchange_rates",
    "marketing_campaigns",
    "products",
    "service_agents",
    "call_center_interactions",
    "call_transcripts",
    "campaign_sends",
    "complaints",
    "digital_events",
    "satisfaction_surveys",
    "transactions",
)


def upgrade() -> None:
    for schema in _SCHEMAS:
        op.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")

    op.create_table(
        "branches",
        sa.Column("branch_id", sa.Text(), primary_key=True),
        sa.Column("branch_code", sa.Text()),
        sa.Column("branch_name", sa.Text()),
        sa.Column("branch_type", sa.Text()),
        sa.Column("address", sa.Text()),
        sa.Column("city", sa.Text()),
        sa.Column("state", sa.Text()),
        sa.Column("country", sa.Text()),
        sa.Column("postal_code", sa.Text()),
        sa.Column("geographic_zone", sa.Text()),
        sa.Column("phone", sa.Text()),
        sa.Column("email", sa.Text()),
        sa.Column("opening_time", sa.Time()),
        sa.Column("closing_time", sa.Time()),
        sa.Column("has_atms", sa.Boolean()),
        sa.Column("atm_count", sa.Integer()),
        sa.Column("has_teller_windows", sa.Boolean()),
        sa.Column("teller_window_count", sa.Integer()),
        sa.Column("latitude", postgresql.DOUBLE_PRECISION()),
        sa.Column("longitude", postgresql.DOUBLE_PRECISION()),
        sa.Column("branch_opening_date", sa.Date()),
        sa.Column("branch_status", sa.Text()),
        schema="bank",
    )

    op.create_table(
        "customers",
        sa.Column("customer_id", sa.Text(), primary_key=True),
        sa.Column("document_number", sa.Text()),
        sa.Column("document_type", sa.Text()),
        sa.Column("first_name", sa.Text()),
        sa.Column("last_name", sa.Text()),
        sa.Column("date_of_birth", sa.Date()),
        sa.Column("gender", sa.Text()),
        sa.Column("email", sa.Text()),
        sa.Column("mobile_phone", sa.Text()),
        sa.Column("landline_phone", sa.Text()),
        sa.Column("address", sa.Text()),
        sa.Column("city", sa.Text()),
        sa.Column("state", sa.Text()),
        sa.Column("country", sa.Text()),
        sa.Column("postal_code", sa.Text()),
        sa.Column("detected_accent", sa.Text()),
        sa.Column("segment", sa.Text()),
        sa.Column("credit_score", postgresql.DOUBLE_PRECISION()),
        sa.Column("estimated_monthly_income", sa.Numeric()),
        sa.Column("occupation", sa.Text()),
        sa.Column("marital_status", sa.Text()),
        sa.Column("education_level", sa.Text()),
        sa.Column("registration_date", sa.DateTime(timezone=True)),
        sa.Column("registration_branch_id", sa.Text()),
        sa.Column("customer_status", sa.Text()),
        sa.Column("last_updated", sa.DateTime(timezone=True)),
        sa.Column("accepts_marketing", sa.Boolean()),
        schema="bank",
    )

    op.create_table(
        "daily_exchange_rates",
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("source_currency", sa.Text(), nullable=False),
        sa.Column("target_currency", sa.Text(), nullable=False),
        sa.Column("exchange_rate", sa.Numeric()),
        sa.Column("buy_rate", sa.Numeric()),
        sa.Column("sell_rate", sa.Numeric()),
        sa.Column("source", sa.Text()),
        sa.PrimaryKeyConstraint("date", "source_currency", "target_currency"),
        schema="bank",
    )

    op.create_table(
        "marketing_campaigns",
        sa.Column("campaign_id", sa.Text(), primary_key=True),
        sa.Column("campaign_name", sa.Text()),
        sa.Column("description", sa.Text()),
        sa.Column("campaign_type", sa.Text()),
        sa.Column("campaign_objective", sa.Text()),
        sa.Column("promoted_product", sa.Text()),
        sa.Column("target_segment", sa.Text()),
        sa.Column("target_country", sa.Text()),
        sa.Column("start_date", sa.Date()),
        sa.Column("end_date", sa.Date()),
        sa.Column("budget", sa.Numeric()),
        sa.Column("campaign_status", sa.Text()),
        sa.Column("expected_conversion_rate", postgresql.DOUBLE_PRECISION()),
        schema="bank",
    )

    op.create_table(
        "products",
        sa.Column("product_id", sa.Text(), primary_key=True),
        sa.Column("customer_id", sa.Text()),
        sa.Column("product_type", sa.Text()),
        sa.Column("product_number", sa.Text()),
        sa.Column("currency", sa.Text()),
        sa.Column("current_balance", sa.Numeric()),
        sa.Column("credit_limit", sa.Numeric()),
        sa.Column("interest_rate", sa.Numeric()),
        sa.Column("opening_date", sa.Date()),
        sa.Column("expiration_date", sa.Date()),
        sa.Column("opening_branch_id", sa.Text()),
        sa.Column("product_status", sa.Text()),
        sa.Column("opening_channel", sa.Text()),
        sa.Column("has_linked_app", sa.Boolean()),
        sa.Column("days_past_due", sa.Integer()),
        sa.Column("last_transaction_date", sa.DateTime(timezone=True)),
        sa.Column("last_updated", sa.DateTime(timezone=True)),
        schema="bank",
    )

    op.create_table(
        "service_agents",
        sa.Column("agent_id", sa.Text(), primary_key=True),
        sa.Column("employee_code", sa.Text()),
        sa.Column("first_name", sa.Text()),
        sa.Column("last_name", sa.Text()),
        sa.Column("email", sa.Text()),
        sa.Column("phone", sa.Text()),
        sa.Column("native_accent", sa.Text()),
        sa.Column("country_of_origin", sa.Text()),
        sa.Column("assigned_branch_id", sa.Text()),
        sa.Column("agent_type", sa.Text()),
        sa.Column("experience_level", sa.Text()),
        sa.Column("languages", sa.Text()),
        sa.Column("specialty", sa.Text()),
        sa.Column("hire_date", sa.Date()),
        sa.Column("avg_csat", postgresql.DOUBLE_PRECISION()),
        sa.Column("total_monthly_interactions", sa.Integer()),
        sa.Column("agent_status", sa.Text()),
        sa.Column("work_shift", sa.Text()),
        schema="bank",
    )

    op.create_table(
        "call_center_interactions",
        sa.Column("interaction_id", sa.Text(), primary_key=True),
        sa.Column("interaction_date", sa.DateTime(timezone=True)),
        sa.Column("process_date", sa.Date()),
        sa.Column("customer_id", sa.Text()),
        sa.Column("agent_id", sa.Text()),
        sa.Column("interaction_type", sa.Text()),
        sa.Column("channel", sa.Text()),
        sa.Column("contact_reason", sa.Text()),
        sa.Column("reason_category", sa.Text()),
        sa.Column("duration_seconds", postgresql.DOUBLE_PRECISION()),
        sa.Column("wait_time_seconds", postgresql.DOUBLE_PRECISION()),
        sa.Column("was_resolved", sa.Boolean()),
        sa.Column("requires_followup", sa.Boolean()),
        sa.Column("detected_sentiment", sa.Text()),
        sa.Column("sentiment_score", postgresql.DOUBLE_PRECISION()),
        sa.Column("customer_detected_accent", sa.Text()),
        sa.Column("agent_used_accent", sa.Text()),
        sa.Column("was_escalated", sa.Boolean()),
        sa.Column("mentioned_products", sa.Text()),
        sa.Column("has_transcript", sa.Boolean()),
        sa.Column("has_recording", sa.Boolean()),
        schema="bank",
    )

    op.create_table(
        "call_transcripts",
        sa.Column("transcript_id", sa.Text(), primary_key=True),
        sa.Column("interaction_id", sa.Text()),
        sa.Column("process_date", sa.Date()),
        sa.Column("customer_id", sa.Text()),
        sa.Column("agent_id", sa.Text()),
        sa.Column("full_text", sa.Text()),
        sa.Column("customer_text", sa.Text()),
        sa.Column("agent_text", sa.Text()),
        sa.Column("detected_language", sa.Text()),
        sa.Column("detected_accent", sa.Text()),
        sa.Column("accent_confidence", postgresql.DOUBLE_PRECISION()),
        sa.Column("detected_keywords", sa.Text()),
        sa.Column("mentioned_entities", sa.Text()),
        sa.Column("detected_intents", sa.Text()),
        sa.Column("main_topics", sa.Text()),
        sa.Column("transcription_model", sa.Text()),
        sa.Column("audio_quality", sa.Text()),
        sa.Column("duration_seconds", postgresql.DOUBLE_PRECISION()),
        schema="bank",
    )

    op.create_table(
        "campaign_sends",
        sa.Column("send_id", sa.Text(), primary_key=True),
        sa.Column("send_date", sa.DateTime(timezone=True)),
        sa.Column("process_date", sa.Date()),
        sa.Column("campaign_id", sa.Text()),
        sa.Column("customer_id", sa.Text()),
        sa.Column("send_channel", sa.Text()),
        sa.Column("template_used", sa.Text()),
        sa.Column("subject", sa.Text()),
        sa.Column("send_status", sa.Text()),
        sa.Column("was_delivered", sa.Boolean()),
        sa.Column("was_opened", sa.Boolean()),
        sa.Column("open_date", sa.DateTime(timezone=True)),
        sa.Column("was_clicked", sa.Boolean()),
        sa.Column("click_date", sa.DateTime(timezone=True)),
        sa.Column("click_count", sa.Integer()),
        sa.Column("had_conversion", sa.Boolean()),
        sa.Column("conversion_date", sa.DateTime(timezone=True)),
        sa.Column("conversion_value", sa.Numeric()),
        sa.Column("open_device", sa.Text()),
        sa.Column("open_country", sa.Text()),
        sa.Column("failure_reason", sa.Text()),
        sa.Column("send_cost", sa.Numeric()),
        schema="bank",
    )

    op.create_table(
        "complaints",
        sa.Column("complaint_id", sa.Text(), primary_key=True),
        sa.Column("creation_date", sa.DateTime(timezone=True)),
        sa.Column("process_date", sa.Date()),
        sa.Column("customer_id", sa.Text()),
        sa.Column("case_type", sa.Text()),
        sa.Column("category", sa.Text()),
        sa.Column("subcategory", sa.Text()),
        sa.Column("reception_channel", sa.Text()),
        sa.Column("affected_product_id", sa.Text()),
        sa.Column("related_branch_id", sa.Text()),
        sa.Column("origin_interaction_id", sa.Text()),
        sa.Column("description", sa.Text()),
        sa.Column("claimed_amount", sa.Numeric()),
        sa.Column("currency", sa.Text()),
        sa.Column("priority", sa.Text()),
        sa.Column("status", sa.Text()),
        sa.Column("assigned_agent_id", sa.Text()),
        sa.Column("assignment_date", sa.DateTime(timezone=True)),
        sa.Column("first_response_date", sa.DateTime(timezone=True)),
        sa.Column("resolution_date", sa.DateTime(timezone=True)),
        sa.Column("closing_date", sa.DateTime(timezone=True)),
        sa.Column("sla_breached", sa.Boolean()),
        sa.Column("resolution_days", postgresql.DOUBLE_PRECISION()),
        sa.Column("resolution", sa.Text()),
        # Money must be exact (human decision, D1-A T9): numeric(14,2), not
        # double precision.
        sa.Column("compensation_granted", sa.Numeric(14, 2)),
        sa.Column("resolution_satisfaction", postgresql.DOUBLE_PRECISION()),
        sa.Column("is_repeat_complainer", sa.Boolean()),
        # Additions for the only bank.* table the app appends to today (D13).
        sa.Column("origin", sa.Text(), nullable=False, server_default="dataset"),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("conversation_id", sa.Uuid(), nullable=True),
        schema="bank",
    )

    op.create_table(
        "digital_events",
        sa.Column("event_id", sa.Text(), primary_key=True),
        sa.Column("event_date", sa.DateTime(timezone=True)),
        sa.Column("process_date", sa.Date()),
        sa.Column("customer_id", sa.Text()),
        sa.Column("session_id", sa.Text()),
        sa.Column("event_type", sa.Text()),
        sa.Column("event_category", sa.Text()),
        sa.Column("channel", sa.Text()),
        sa.Column("platform", sa.Text()),
        sa.Column("browser", sa.Text()),
        sa.Column("app_version", sa.Text()),
        sa.Column("page_url", sa.Text()),
        sa.Column("page_title", sa.Text()),
        sa.Column("action", sa.Text()),
        sa.Column("element_id", sa.Text()),
        sa.Column("product_id", sa.Text()),
        sa.Column("event_value", postgresql.DOUBLE_PRECISION()),
        sa.Column("duration_seconds", postgresql.DOUBLE_PRECISION()),
        sa.Column("ip_address", sa.Text()),
        sa.Column("ip_country", sa.Text()),
        sa.Column("ip_city", sa.Text()),
        sa.Column("is_mobile", sa.Boolean()),
        sa.Column("referrer", sa.Text()),
        sa.Column("utm_source", sa.Text()),
        sa.Column("utm_medium", sa.Text()),
        sa.Column("utm_campaign", sa.Text()),
        schema="bank",
    )

    op.create_table(
        "satisfaction_surveys",
        sa.Column("survey_id", sa.Text(), primary_key=True),
        sa.Column("survey_date", sa.DateTime(timezone=True)),
        sa.Column("process_date", sa.Date()),
        sa.Column("interaction_id", sa.Text()),
        sa.Column("customer_id", sa.Text()),
        sa.Column("agent_id", sa.Text()),
        sa.Column("survey_type", sa.Text()),
        sa.Column("send_channel", sa.Text()),
        sa.Column("main_score", postgresql.DOUBLE_PRECISION()),
        sa.Column("nps_category", sa.Text()),
        sa.Column("question_1_text", sa.Text()),
        sa.Column("question_1_response", postgresql.DOUBLE_PRECISION()),
        sa.Column("question_2_text", sa.Text()),
        sa.Column("question_2_response", postgresql.DOUBLE_PRECISION()),
        sa.Column("question_3_text", sa.Text()),
        sa.Column("question_3_response", postgresql.DOUBLE_PRECISION()),
        sa.Column("open_comments", sa.Text()),
        sa.Column("comment_sentiment", sa.Text()),
        sa.Column("response_time_hours", postgresql.DOUBLE_PRECISION()),
        sa.Column("campaign_response_rate", postgresql.DOUBLE_PRECISION()),
        schema="bank",
    )

    op.create_table(
        "transactions",
        sa.Column("transaction_id", sa.Text(), primary_key=True),
        sa.Column("transaction_date", sa.DateTime(timezone=True)),
        sa.Column("process_date", sa.Date()),
        sa.Column("product_id", sa.Text()),
        sa.Column("customer_id", sa.Text()),
        sa.Column("transaction_type", sa.Text()),
        sa.Column("transaction_category", sa.Text()),
        sa.Column("amount", sa.Numeric()),
        sa.Column("currency", sa.Text()),
        sa.Column("amount_usd", sa.Numeric()),
        sa.Column("channel", sa.Text()),
        sa.Column("branch_id", sa.Text()),
        sa.Column("merchant_name", sa.Text()),
        sa.Column("merchant_category", sa.Text()),
        sa.Column("transaction_country", sa.Text()),
        sa.Column("transaction_city", sa.Text()),
        sa.Column("transaction_status", sa.Text()),
        sa.Column("response_code", sa.Text()),
        sa.Column("is_fraud", sa.Boolean()),
        sa.Column("fraud_score", sa.Numeric()),
        sa.Column("latitude", postgresql.DOUBLE_PRECISION()),
        sa.Column("longitude", postgresql.DOUBLE_PRECISION()),
        schema="bank",
    )

    # The four proposed indexes (03 §6) supporting the conversation domain's
    # read paths: a customer's cards by type, and a card/customer's recent
    # transactions and complaints.
    op.create_index(
        "ix_products_customer_id_product_type",
        "products",
        ["customer_id", "product_type"],
        schema="bank",
    )
    op.create_index(
        "ix_transactions_customer_id_product_id_transaction_date",
        "transactions",
        ["customer_id", "product_id", sa.text("transaction_date DESC")],
        schema="bank",
    )
    op.create_index(
        "ix_transactions_product_id_transaction_status_transaction_date",
        "transactions",
        ["product_id", "transaction_status", sa.text("transaction_date DESC")],
        schema="bank",
    )
    op.create_index(
        "ix_complaints_customer_id_creation_date",
        "complaints",
        ["customer_id", sa.text("creation_date DESC")],
        schema="bank",
    )

    op.create_table(
        "system_metadata",
        sa.Column("run_id", sa.Text(), primary_key=True),
        sa.Column("load_date", sa.Date(), nullable=False),
        sa.Column("max_data_date", sa.Date(), nullable=False),
        sa.Column("date_offset_days", sa.Integer(), nullable=False),
        sa.Column("manifest_sha256", sa.Text(), nullable=False),
        sa.Column("policy_hash", sa.Text(), nullable=True),
        sa.Column(
            "loaded_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        schema="app",
    )


def downgrade() -> None:
    op.drop_table("system_metadata", schema="app")

    op.drop_index("ix_complaints_customer_id_creation_date", table_name="complaints", schema="bank")
    op.drop_index(
        "ix_transactions_product_id_transaction_status_transaction_date",
        table_name="transactions",
        schema="bank",
    )
    op.drop_index(
        "ix_transactions_customer_id_product_id_transaction_date",
        table_name="transactions",
        schema="bank",
    )
    op.drop_index("ix_products_customer_id_product_type", table_name="products", schema="bank")

    for table in reversed(_BANK_TABLES):
        op.drop_table(table, schema="bank")

    for schema in reversed(_SCHEMAS):
        op.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
