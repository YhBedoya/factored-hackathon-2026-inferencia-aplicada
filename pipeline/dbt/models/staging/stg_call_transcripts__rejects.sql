-- Typed, deduped staging for bank.call_transcripts (D8). No date shift here
-- (D11); `nullif(trim(x), '')` runs before every cast so a blank
-- source string becomes SQL NULL instead of an empty string or a
-- cast error. TIMESTAMP columns stay naive (no `timestamptz`): the
-- UTC interpretation and the shift both happen in serving (T11).
-- This sibling keeps the duplicate rows `stg_call_transcripts` drops.
with source as (
    select * from {{ source('raw', 'call_transcripts') }}
),

typed as (
    select
        cast(nullif(trim(transcript_id), '') as text) as transcript_id,
        cast(nullif(trim(interaction_id), '') as text) as interaction_id,
        cast(nullif(trim(process_date), '') as date) as process_date,
        cast(nullif(trim(customer_id), '') as text) as customer_id,
        cast(nullif(trim(agent_id), '') as text) as agent_id,
        cast(nullif(trim(full_text), '') as text) as full_text,
        cast(nullif(trim(customer_text), '') as text) as customer_text,
        cast(nullif(trim(agent_text), '') as text) as agent_text,
        cast(nullif(trim(detected_language), '') as text) as detected_language,
        cast(nullif(trim(detected_accent), '') as text) as detected_accent,
        cast(nullif(trim(accent_confidence), '') as double precision) as accent_confidence,
        cast(nullif(trim(detected_keywords), '') as text) as detected_keywords,
        cast(nullif(trim(mentioned_entities), '') as text) as mentioned_entities,
        cast(nullif(trim(detected_intents), '') as text) as detected_intents,
        cast(nullif(trim(main_topics), '') as text) as main_topics,
        cast(nullif(trim(transcription_model), '') as text) as transcription_model,
        cast(nullif(trim(audio_quality), '') as text) as audio_quality,
        cast(nullif(trim(duration_seconds), '') as double precision) as duration_seconds,
        {{ dedup_row_number('transcript_id') }} as dedup_row_number
    from source
)

select * exclude (dedup_row_number)
from typed
where dedup_row_number > 1
