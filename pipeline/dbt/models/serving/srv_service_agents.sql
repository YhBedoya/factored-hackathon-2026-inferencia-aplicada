-- Final column set for bank.service_agents, in the migration's column order
-- (0001, T11). `hire_date` is shifted (D11).
select
    agent_id,
    employee_code,
    first_name,
    last_name,
    email,
    phone,
    native_accent,
    country_of_origin,
    assigned_branch_id,
    agent_type,
    experience_level,
    languages,
    specialty,
    {{ shift_date('hire_date') }} as hire_date,
    avg_csat,
    total_monthly_interactions,
    agent_status,
    work_shift
from {{ ref('stg_service_agents') }}
