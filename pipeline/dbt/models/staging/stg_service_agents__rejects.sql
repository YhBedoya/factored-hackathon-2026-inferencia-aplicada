-- Typed, deduped staging for bank.service_agents (D8). No date shift here
-- (D11); `nullif(trim(x), '')` runs before every cast so a blank
-- source string becomes SQL NULL instead of an empty string or a
-- cast error. TIMESTAMP columns stay naive (no `timestamptz`): the
-- UTC interpretation and the shift both happen in serving (T11).
-- This sibling keeps the duplicate rows `stg_service_agents` drops.
with source as (
    select * from {{ source('raw', 'service_agents') }}
),

typed as (
    select
        cast(nullif(trim(agent_id), '') as text) as agent_id,
        cast(nullif(trim(employee_code), '') as text) as employee_code,
        cast(nullif(trim(first_name), '') as text) as first_name,
        cast(nullif(trim(last_name), '') as text) as last_name,
        cast(nullif(trim(email), '') as text) as email,
        cast(nullif(trim(phone), '') as text) as phone,
        cast(nullif(trim(native_accent), '') as text) as native_accent,
        cast(nullif(trim(country_of_origin), '') as text) as country_of_origin,
        cast(nullif(trim(assigned_branch_id), '') as text) as assigned_branch_id,
        cast(nullif(trim(agent_type), '') as text) as agent_type,
        cast(nullif(trim(experience_level), '') as text) as experience_level,
        cast(nullif(trim(languages), '') as text) as languages,
        cast(nullif(trim(specialty), '') as text) as specialty,
        cast(nullif(trim(hire_date), '') as date) as hire_date,
        cast(nullif(trim(avg_csat), '') as double precision) as avg_csat,
        cast(nullif(trim(total_monthly_interactions), '') as integer) as total_monthly_interactions,
        cast(nullif(trim(agent_status), '') as text) as agent_status,
        cast(nullif(trim(work_shift), '') as text) as work_shift,
        {{ dedup_row_number('agent_id') }} as dedup_row_number
    from source
)

select * exclude (dedup_row_number)
from typed
where dedup_row_number > 1
