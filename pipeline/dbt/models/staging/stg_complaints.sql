-- Typed, deduped staging for bank.complaints (D8). No date shift here
-- (D11); `nullif(trim(x), '')` runs before every cast so a blank
-- source string becomes SQL NULL instead of an empty string or a
-- cast error. TIMESTAMP columns stay naive (no `timestamptz`): the
-- UTC interpretation and the shift both happen in serving (T11). The
-- app-only additions (`origin`, `created_at`, `conversation_id`, D13) aren't
-- source columns, so they aren't cast here.
with source as (
    select * from {{ source('raw', 'complaints') }}
),

typed as (
    select
        cast(nullif(trim(complaint_id), '') as text) as complaint_id,
        cast(nullif(trim(creation_date), '') as timestamp) as creation_date,
        cast(nullif(trim(process_date), '') as date) as process_date,
        cast(nullif(trim(customer_id), '') as text) as customer_id,
        cast(nullif(trim(case_type), '') as text) as case_type,
        cast(nullif(trim(category), '') as text) as category,
        cast(nullif(trim(subcategory), '') as text) as subcategory,
        cast(nullif(trim(reception_channel), '') as text) as reception_channel,
        cast(nullif(trim(affected_product_id), '') as text) as affected_product_id,
        cast(nullif(trim(related_branch_id), '') as text) as related_branch_id,
        cast(nullif(trim(origin_interaction_id), '') as text) as origin_interaction_id,
        cast(nullif(trim(description), '') as text) as description,
        cast(nullif(trim(claimed_amount), '') as numeric) as claimed_amount,
        cast(nullif(trim(currency), '') as text) as currency,
        cast(nullif(trim(priority), '') as text) as priority,
        cast(nullif(trim(status), '') as text) as status,
        cast(nullif(trim(assigned_agent_id), '') as text) as assigned_agent_id,
        cast(nullif(trim(assignment_date), '') as timestamp) as assignment_date,
        cast(nullif(trim(first_response_date), '') as timestamp) as first_response_date,
        cast(nullif(trim(resolution_date), '') as timestamp) as resolution_date,
        cast(nullif(trim(closing_date), '') as timestamp) as closing_date,
        cast(nullif(trim(sla_breached), '') as boolean) as sla_breached,
        cast(nullif(trim(resolution_days), '') as double precision) as resolution_days,
        cast(nullif(trim(resolution), '') as text) as resolution,
        -- Money must be exact (human decision, D1-A T9): decimal(14,2),
        -- matching 0001's `numeric(14,2)` for this column.
        cast(nullif(trim(compensation_granted), '') as decimal(14, 2)) as compensation_granted,
        cast(nullif(trim(resolution_satisfaction), '') as double precision) as resolution_satisfaction,
        cast(nullif(trim(is_repeat_complainer), '') as boolean) as is_repeat_complainer,
        {{ dedup_row_number('complaint_id') }} as dedup_row_number
    from source
)

select * exclude (dedup_row_number)
from typed
where dedup_row_number = 1
