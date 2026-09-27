-- Typed, deduped staging for bank.campaign_sends (D8). No date shift here
-- (D11); `nullif(trim(x), '')` runs before every cast so a blank
-- source string becomes SQL NULL instead of an empty string or a
-- cast error. TIMESTAMP columns stay naive (no `timestamptz`): the
-- UTC interpretation and the shift both happen in serving (T11).
-- This sibling keeps the duplicate rows `stg_campaign_sends` drops.
with source as (
    select * from {{ source('raw', 'campaign_sends') }}
),

typed as (
    select
        cast(nullif(trim(send_id), '') as text) as send_id,
        cast(nullif(trim(send_date), '') as timestamp) as send_date,
        cast(nullif(trim(process_date), '') as date) as process_date,
        cast(nullif(trim(campaign_id), '') as text) as campaign_id,
        cast(nullif(trim(customer_id), '') as text) as customer_id,
        cast(nullif(trim(send_channel), '') as text) as send_channel,
        cast(nullif(trim(template_used), '') as text) as template_used,
        cast(nullif(trim(subject), '') as text) as subject,
        cast(nullif(trim(send_status), '') as text) as send_status,
        cast(nullif(trim(was_delivered), '') as boolean) as was_delivered,
        cast(nullif(trim(was_opened), '') as boolean) as was_opened,
        cast(nullif(trim(open_date), '') as timestamp) as open_date,
        cast(nullif(trim(was_clicked), '') as boolean) as was_clicked,
        cast(nullif(trim(click_date), '') as timestamp) as click_date,
        cast(nullif(trim(click_count), '') as integer) as click_count,
        cast(nullif(trim(had_conversion), '') as boolean) as had_conversion,
        cast(nullif(trim(conversion_date), '') as timestamp) as conversion_date,
        cast(nullif(trim(conversion_value), '') as numeric) as conversion_value,
        cast(nullif(trim(open_device), '') as text) as open_device,
        cast(nullif(trim(open_country), '') as text) as open_country,
        cast(nullif(trim(failure_reason), '') as text) as failure_reason,
        cast(nullif(trim(send_cost), '') as numeric) as send_cost,
        {{ dedup_row_number('send_id') }} as dedup_row_number
    from source
)

select * exclude (dedup_row_number)
from typed
where dedup_row_number > 1
