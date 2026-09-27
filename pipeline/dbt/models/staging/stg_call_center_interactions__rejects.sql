-- Typed, deduped staging for bank.call_center_interactions (D8). No date
-- shift here (D11); `nullif(trim(x), '')` runs before every cast so a blank
-- source string becomes SQL NULL instead of an empty string or a
-- cast error. TIMESTAMP columns stay naive (no `timestamptz`): the
-- UTC interpretation and the shift both happen in serving (T11).
-- This sibling keeps the duplicate rows `stg_call_center_interactions` drops.
with source as (
    select * from {{ source('raw', 'call_center_interactions') }}
),

typed as (
    select
        cast(nullif(trim(interaction_id), '') as text) as interaction_id,
        cast(nullif(trim(interaction_date), '') as timestamp) as interaction_date,
        cast(nullif(trim(process_date), '') as date) as process_date,
        cast(nullif(trim(customer_id), '') as text) as customer_id,
        cast(nullif(trim(agent_id), '') as text) as agent_id,
        cast(nullif(trim(interaction_type), '') as text) as interaction_type,
        cast(nullif(trim(channel), '') as text) as channel,
        cast(nullif(trim(contact_reason), '') as text) as contact_reason,
        cast(nullif(trim(reason_category), '') as text) as reason_category,
        cast(nullif(trim(duration_seconds), '') as double precision) as duration_seconds,
        cast(nullif(trim(wait_time_seconds), '') as double precision) as wait_time_seconds,
        cast(nullif(trim(was_resolved), '') as boolean) as was_resolved,
        cast(nullif(trim(requires_followup), '') as boolean) as requires_followup,
        cast(nullif(trim(detected_sentiment), '') as text) as detected_sentiment,
        cast(nullif(trim(sentiment_score), '') as double precision) as sentiment_score,
        cast(nullif(trim(customer_detected_accent), '') as text) as customer_detected_accent,
        cast(nullif(trim(agent_used_accent), '') as text) as agent_used_accent,
        cast(nullif(trim(was_escalated), '') as boolean) as was_escalated,
        cast(nullif(trim(mentioned_products), '') as text) as mentioned_products,
        cast(nullif(trim(has_transcript), '') as boolean) as has_transcript,
        cast(nullif(trim(has_recording), '') as boolean) as has_recording,
        {{ dedup_row_number('interaction_id') }} as dedup_row_number
    from source
)

select * exclude (dedup_row_number)
from typed
where dedup_row_number > 1
