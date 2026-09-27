-- Final column set for bank.campaign_sends, in the migration's column order
-- (0001, T11). `send_date`, `process_date`, `open_date`, `click_date` and
-- `conversion_date` are shifted (D11).
select
    send_id,
    {{ shift_timestamp('send_date') }} as send_date,
    {{ shift_date('process_date') }} as process_date,
    campaign_id,
    customer_id,
    send_channel,
    template_used,
    subject,
    send_status,
    was_delivered,
    was_opened,
    {{ shift_timestamp('open_date') }} as open_date,
    was_clicked,
    {{ shift_timestamp('click_date') }} as click_date,
    click_count,
    had_conversion,
    {{ shift_timestamp('conversion_date') }} as conversion_date,
    conversion_value,
    open_device,
    open_country,
    failure_reason,
    send_cost
from {{ ref('stg_campaign_sends') }}
