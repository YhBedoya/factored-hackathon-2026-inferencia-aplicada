-- Final column set for bank.call_transcripts, in the migration's column
-- order (0001, T11). `process_date` is shifted (D11).
select
    transcript_id,
    interaction_id,
    {{ shift_date('process_date') }} as process_date,
    customer_id,
    agent_id,
    full_text,
    customer_text,
    agent_text,
    detected_language,
    detected_accent,
    accent_confidence,
    detected_keywords,
    mentioned_entities,
    detected_intents,
    main_topics,
    transcription_model,
    audio_quality,
    duration_seconds
from {{ ref('stg_call_transcripts') }}
