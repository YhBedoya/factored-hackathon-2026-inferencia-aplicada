-- Final column set for bank.call_center_interactions, in the migration's
-- column order (0001, T11). `interaction_date` and `process_date` are
-- shifted (D11).
select
    interaction_id,
    {{ shift_timestamp('interaction_date') }} as interaction_date,
    {{ shift_date('process_date') }} as process_date,
    customer_id,
    agent_id,
    interaction_type,
    channel,
    contact_reason,
    reason_category,
    duration_seconds,
    wait_time_seconds,
    was_resolved,
    requires_followup,
    detected_sentiment,
    sentiment_score,
    customer_detected_accent,
    agent_used_accent,
    was_escalated,
    mentioned_products,
    has_transcript,
    has_recording
from {{ ref('stg_call_center_interactions') }}
