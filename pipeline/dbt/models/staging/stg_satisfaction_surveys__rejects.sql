-- Typed, deduped staging for bank.satisfaction_surveys (D8). No date shift
-- here (D11); `nullif(trim(x), '')` runs before every cast so a blank
-- source string becomes SQL NULL instead of an empty string or a
-- cast error. TIMESTAMP columns stay naive (no `timestamptz`): the
-- UTC interpretation and the shift both happen in serving (T11).
-- This sibling keeps the duplicate rows `stg_satisfaction_surveys` drops.
with source as (
    select * from {{ source('raw', 'satisfaction_surveys') }}
),

typed as (
    select
        cast(nullif(trim(survey_id), '') as text) as survey_id,
        cast(nullif(trim(survey_date), '') as timestamp) as survey_date,
        cast(nullif(trim(process_date), '') as date) as process_date,
        cast(nullif(trim(interaction_id), '') as text) as interaction_id,
        cast(nullif(trim(customer_id), '') as text) as customer_id,
        cast(nullif(trim(agent_id), '') as text) as agent_id,
        cast(nullif(trim(survey_type), '') as text) as survey_type,
        cast(nullif(trim(send_channel), '') as text) as send_channel,
        cast(nullif(trim(main_score), '') as double precision) as main_score,
        cast(nullif(trim(nps_category), '') as text) as nps_category,
        cast(nullif(trim(question_1_text), '') as text) as question_1_text,
        cast(nullif(trim(question_1_response), '') as double precision) as question_1_response,
        cast(nullif(trim(question_2_text), '') as text) as question_2_text,
        cast(nullif(trim(question_2_response), '') as double precision) as question_2_response,
        cast(nullif(trim(question_3_text), '') as text) as question_3_text,
        cast(nullif(trim(question_3_response), '') as double precision) as question_3_response,
        cast(nullif(trim(open_comments), '') as text) as open_comments,
        cast(nullif(trim(comment_sentiment), '') as text) as comment_sentiment,
        cast(nullif(trim(response_time_hours), '') as double precision) as response_time_hours,
        cast(nullif(trim(campaign_response_rate), '') as double precision) as campaign_response_rate,
        {{ dedup_row_number('survey_id') }} as dedup_row_number
    from source
)

select * exclude (dedup_row_number)
from typed
where dedup_row_number > 1
