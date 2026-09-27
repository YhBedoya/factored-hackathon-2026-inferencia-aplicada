-- Final column set for bank.products, in the migration's column order
-- (0001, T11). `opening_date`/`expiration_date` and the two TIMESTAMPs are
-- shifted (D11).
select
    product_id,
    customer_id,
    product_type,
    product_number,
    currency,
    current_balance,
    credit_limit,
    interest_rate,
    {{ shift_date('opening_date') }} as opening_date,
    {{ shift_date('expiration_date') }} as expiration_date,
    opening_branch_id,
    product_status,
    opening_channel,
    has_linked_app,
    days_past_due,
    {{ shift_timestamp('last_transaction_date') }} as last_transaction_date,
    {{ shift_timestamp('last_updated') }} as last_updated
from {{ ref('stg_products') }}
