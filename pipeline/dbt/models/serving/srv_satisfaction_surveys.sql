-- Final column set for bank.satisfaction_surveys, in the migration's column
-- order (0001, T11). `survey_date` and `process_date` are shifted (D11).
select
    survey_id,
    {{ shift_timestamp('survey_date') }} as survey_date,
    {{ shift_date('process_date') }} as process_date,
    interaction_id,
    customer_id,
    agent_id,
    survey_type,
    send_channel,
    main_score,
    nps_category,
    question_1_text,
    question_1_response,
    question_2_text,
    question_2_response,
    question_3_text,
    question_3_response,
    open_comments,
    comment_sentiment,
    response_time_hours,
    campaign_response_rate
from {{ ref('stg_satisfaction_surveys') }}
