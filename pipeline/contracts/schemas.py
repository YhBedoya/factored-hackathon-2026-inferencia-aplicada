"""One Pandera schema per raw table (D17).

Raw Parquet is all VARCHAR, so the type checks are "coercible to" checks that
mirror each staging model's cast list (`dbt/models/staging/stg_<t>.sql`). Blank
strings count as NULL, like the models' `nullif(trim(x), '')`. The PK is the
column the model's `dedup_row_number` partitions by.
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
import pandera.pandas as pa
import yaml

ALIASES_PATH = Path(__file__).with_name("aliases.yaml")

# table -> (pk columns, {column: kind}); kinds: text ts date time bool int num.
TABLE_SPECS: dict[str, tuple[str, dict[str, str]]] = {
    "branches": (
        "branch_id",
        {
            "branch_id": "text",
            "branch_code": "text",
            "branch_name": "text",
            "branch_type": "text",
            "address": "text",
            "city": "text",
            "state": "text",
            "country": "text",
            "postal_code": "text",
            "geographic_zone": "text",
            "phone": "text",
            "email": "text",
            "opening_time": "time",
            "closing_time": "time",
            "has_atms": "bool",
            "atm_count": "int",
            "has_teller_windows": "bool",
            "teller_window_count": "int",
            "latitude": "num",
            "longitude": "num",
            "branch_opening_date": "date",
            "branch_status": "text",
        },
    ),
    "call_center_interactions": (
        "interaction_id",
        {
            "interaction_id": "text",
            "interaction_date": "ts",
            "process_date": "date",
            "customer_id": "text",
            "agent_id": "text",
            "interaction_type": "text",
            "channel": "text",
            "contact_reason": "text",
            "reason_category": "text",
            "duration_seconds": "num",
            "wait_time_seconds": "num",
            "was_resolved": "bool",
            "requires_followup": "bool",
            "detected_sentiment": "text",
            "sentiment_score": "num",
            "customer_detected_accent": "text",
            "agent_used_accent": "text",
            "was_escalated": "bool",
            "mentioned_products": "text",
            "has_transcript": "bool",
            "has_recording": "bool",
        },
    ),
    "call_transcripts": (
        "transcript_id",
        {
            "transcript_id": "text",
            "interaction_id": "text",
            "process_date": "date",
            "customer_id": "text",
            "agent_id": "text",
            "full_text": "text",
            "customer_text": "text",
            "agent_text": "text",
            "detected_language": "text",
            "detected_accent": "text",
            "accent_confidence": "num",
            "detected_keywords": "text",
            "mentioned_entities": "text",
            "detected_intents": "text",
            "main_topics": "text",
            "transcription_model": "text",
            "audio_quality": "text",
            "duration_seconds": "num",
        },
    ),
    "campaign_sends": (
        "send_id",
        {
            "send_id": "text",
            "send_date": "ts",
            "process_date": "date",
            "campaign_id": "text",
            "customer_id": "text",
            "send_channel": "text",
            "template_used": "text",
            "subject": "text",
            "send_status": "text",
            "was_delivered": "bool",
            "was_opened": "bool",
            "open_date": "ts",
            "was_clicked": "bool",
            "click_date": "ts",
            "click_count": "int",
            "had_conversion": "bool",
            "conversion_date": "ts",
            "conversion_value": "num",
            "open_device": "text",
            "open_country": "text",
            "failure_reason": "text",
            "send_cost": "num",
        },
    ),
    "complaints": (
        "complaint_id",
        {
            "complaint_id": "text",
            "creation_date": "ts",
            "process_date": "date",
            "customer_id": "text",
            "case_type": "text",
            "category": "text",
            "subcategory": "text",
            "reception_channel": "text",
            "affected_product_id": "text",
            "related_branch_id": "text",
            "origin_interaction_id": "text",
            "description": "text",
            "claimed_amount": "num",
            "currency": "text",
            "priority": "text",
            "status": "text",
            "assigned_agent_id": "text",
            "assignment_date": "ts",
            "first_response_date": "ts",
            "resolution_date": "ts",
            "closing_date": "ts",
            "sla_breached": "bool",
            "resolution_days": "num",
            "resolution": "text",
            "resolution_satisfaction": "num",
            "is_repeat_complainer": "bool",
        },
    ),
    "customers": (
        "customer_id",
        {
            "customer_id": "text",
            "document_number": "text",
            "document_type": "text",
            "first_name": "text",
            "last_name": "text",
            "date_of_birth": "date",
            "gender": "text",
            "email": "text",
            "mobile_phone": "text",
            "landline_phone": "text",
            "address": "text",
            "city": "text",
            "state": "text",
            "country": "text",
            "postal_code": "text",
            "detected_accent": "text",
            "segment": "text",
            "credit_score": "num",
            "estimated_monthly_income": "num",
            "occupation": "text",
            "marital_status": "text",
            "education_level": "text",
            "registration_date": "ts",
            "registration_branch_id": "text",
            "customer_status": "text",
            "last_updated": "ts",
            "accepts_marketing": "bool",
        },
    ),
    "daily_exchange_rates": (
        "date,source_currency,target_currency",
        {
            "date": "date",
            "source_currency": "text",
            "target_currency": "text",
            "exchange_rate": "num",
            "buy_rate": "num",
            "sell_rate": "num",
            "source": "text",
        },
    ),
    "digital_events": (
        "event_id",
        {
            "event_id": "text",
            "event_date": "ts",
            "process_date": "date",
            "customer_id": "text",
            "session_id": "text",
            "event_type": "text",
            "event_category": "text",
            "channel": "text",
            "platform": "text",
            "browser": "text",
            "app_version": "text",
            "page_url": "text",
            "page_title": "text",
            "action": "text",
            "element_id": "text",
            "product_id": "text",
            "event_value": "num",
            "duration_seconds": "num",
            "ip_address": "text",
            "ip_country": "text",
            "ip_city": "text",
            "is_mobile": "bool",
            "referrer": "text",
            "utm_source": "text",
            "utm_medium": "text",
            "utm_campaign": "text",
        },
    ),
    "marketing_campaigns": (
        "campaign_id",
        {
            "campaign_id": "text",
            "campaign_name": "text",
            "description": "text",
            "campaign_type": "text",
            "campaign_objective": "text",
            "promoted_product": "text",
            "target_segment": "text",
            "target_country": "text",
            "start_date": "date",
            "end_date": "date",
            "budget": "num",
            "campaign_status": "text",
            "expected_conversion_rate": "num",
        },
    ),
    "products": (
        "product_id",
        {
            "product_id": "text",
            "customer_id": "text",
            "product_type": "text",
            "product_number": "text",
            "currency": "text",
            "current_balance": "num",
            "credit_limit": "num",
            "interest_rate": "num",
            "opening_date": "date",
            "expiration_date": "date",
            "opening_branch_id": "text",
            "product_status": "text",
            "opening_channel": "text",
            "has_linked_app": "bool",
            "days_past_due": "int",
            "last_transaction_date": "ts",
            "last_updated": "ts",
        },
    ),
    "satisfaction_surveys": (
        "survey_id",
        {
            "survey_id": "text",
            "survey_date": "ts",
            "process_date": "date",
            "interaction_id": "text",
            "customer_id": "text",
            "agent_id": "text",
            "survey_type": "text",
            "send_channel": "text",
            "main_score": "num",
            "nps_category": "text",
            "question_1_text": "text",
            "question_1_response": "num",
            "question_2_text": "text",
            "question_2_response": "num",
            "question_3_text": "text",
            "question_3_response": "num",
            "open_comments": "text",
            "comment_sentiment": "text",
            "response_time_hours": "num",
            "campaign_response_rate": "num",
        },
    ),
    "service_agents": (
        "agent_id",
        {
            "agent_id": "text",
            "employee_code": "text",
            "first_name": "text",
            "last_name": "text",
            "email": "text",
            "phone": "text",
            "native_accent": "text",
            "country_of_origin": "text",
            "assigned_branch_id": "text",
            "agent_type": "text",
            "experience_level": "text",
            "languages": "text",
            "specialty": "text",
            "hire_date": "date",
            "avg_csat": "num",
            "total_monthly_interactions": "int",
            "agent_status": "text",
            "work_shift": "text",
        },
    ),
    "transactions": (
        "transaction_id",
        {
            "transaction_id": "text",
            "transaction_date": "ts",
            "process_date": "date",
            "product_id": "text",
            "customer_id": "text",
            "transaction_type": "text",
            "transaction_category": "text",
            "amount": "num",
            "currency": "text",
            "amount_usd": "num",
            "channel": "text",
            "branch_id": "text",
            "merchant_name": "text",
            "merchant_category": "text",
            "transaction_country": "text",
            "transaction_city": "text",
            "transaction_status": "text",
            "response_code": "text",
            "is_fraud": "bool",
            "fraud_score": "num",
            "latitude": "num",
            "longitude": "num",
        },
    ),
}

# Enum domains from `dbt/models/serving/schema.yml` accepted_values.
ENUMS: dict[tuple[str, str], tuple[str, ...]] = {
    ("customers", "country"): ("Argentina", "Colombia", "México"),
    ("customers", "customer_status"): ("Active", "Closed", "Inactive", "Suspended"),
    ("products", "product_type"): (
        "Cuenta Ahorro",
        "Cuenta Corriente",
        "Inversión",
        "Préstamo Hipotecario",
        "Préstamo Personal",
        "Seguro",
        "Tarjeta Crédito",
        "Tarjeta Débito",
    ),
    ("products", "product_status"): ("Active", "Blocked", "Closed", "Suspended"),
    ("transactions", "transaction_status"): ("Approved", "Declined", "Pending", "Reversed"),
}

RANGES: dict[tuple[str, str], tuple[float, float]] = {
    ("transactions", "fraud_score"): (0, 100),
    ("customers", "credit_score"): (300, 850),
}

_BOOL_VALUES = {"true", "false", "t", "f", "1", "0", "yes", "no", "y", "n"}
_TIME_RE = re.compile(r"^\d{1,2}:\d{2}(:\d{2}(\.\d+)?)?$")


def load_aliases() -> dict[str, dict[str, str]]:
    """`{table: {raw_name: canonical_name}}`, shared with dbt's `column_aliases` var."""
    with ALIASES_PATH.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _numeric(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce")


def _coercible(kind: str, s: pd.Series) -> pd.Series:
    """True where the (non-null) value casts to `kind`."""
    if kind == "num":
        return _numeric(s).notna()
    if kind == "int":
        n = _numeric(s)
        return n.notna() & (n == n.round())
    if kind in ("ts", "date"):
        return pd.to_datetime(s, errors="coerce", format="mixed").notna()
    if kind == "bool":
        return s.str.lower().isin(_BOOL_VALUES)
    if kind == "time":
        return s.str.match(_TIME_RE).fillna(False).astype(bool)
    return pd.Series(True, index=s.index)


def _column(table: str, name: str, kind: str, pk: tuple[str, ...]) -> pa.Column:
    checks: list[pa.Check] = []
    if kind != "text":
        checks.append(pa.Check(lambda s, k=kind: _coercible(k, s), name=f"{kind}_coercible"))
    if (table, name) in ENUMS:
        checks.append(pa.Check.isin(list(ENUMS[table, name]), name="enum"))
    if (table, name) in RANGES:
        lo, hi = RANGES[table, name]
        # Non-numeric values are the type check's failures; don't count them twice.
        checks.append(
            pa.Check(
                lambda s, lo=lo, hi=hi: (n := _numeric(s)).isna() | n.between(lo, hi),
                name="range",
            )
        )
    return pa.Column(nullable=name not in pk, checks=checks)


def _build(table: str) -> pa.DataFrameSchema:
    pk_spec, cols = TABLE_SPECS[table]
    pk = tuple(pk_spec.split(","))
    return pa.DataFrameSchema({n: _column(table, n, k, pk) for n, k in cols.items()}, name=table)


SCHEMAS: dict[str, pa.DataFrameSchema] = {t: _build(t) for t in TABLE_SPECS}


def primary_key(table: str) -> tuple[str, ...]:
    return tuple(TABLE_SPECS[table][0].split(","))
