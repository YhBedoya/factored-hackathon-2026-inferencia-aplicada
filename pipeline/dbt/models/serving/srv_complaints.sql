-- Final column set for bank.complaints, in the migration's column order
-- (0001, T11), excluding the app-only additions `origin`, `created_at` and
-- `conversation_id` (D13): those take their column defaults / NULL at load,
-- they are never populated from the dataset. `creation_date`,
-- `process_date`, `assignment_date`, `first_response_date`,
-- `resolution_date` and `closing_date` are shifted (D11).
select
    complaint_id,
    {{ shift_timestamp('creation_date') }} as creation_date,
    {{ shift_date('process_date') }} as process_date,
    customer_id,
    case_type,
    category,
    subcategory,
    reception_channel,
    affected_product_id,
    related_branch_id,
    origin_interaction_id,
    description,
    claimed_amount,
    currency,
    priority,
    status,
    assigned_agent_id,
    {{ shift_timestamp('assignment_date') }} as assignment_date,
    {{ shift_timestamp('first_response_date') }} as first_response_date,
    {{ shift_timestamp('resolution_date') }} as resolution_date,
    {{ shift_timestamp('closing_date') }} as closing_date,
    sla_breached,
    resolution_days,
    resolution,
    -- Money must be exact (human decision, D1-A T9): decimal(14,2), matching
    -- 0001's `numeric(14,2)` for this column. No shift: not a date/timestamp.
    compensation_granted,
    resolution_satisfaction,
    is_repeat_complainer
from {{ ref('stg_complaints') }}
