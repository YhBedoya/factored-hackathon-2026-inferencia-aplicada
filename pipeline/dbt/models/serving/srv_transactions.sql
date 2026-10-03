-- Final column set for bank.transactions, in the migration's column order
-- (0001, T11). `transaction_date` and `process_date` are shifted (D11).
select
    transaction_id,
    {{ shift_timestamp('transaction_date') }} as transaction_date,
    {{ shift_date('process_date') }} as process_date,
    product_id,
    customer_id,
    transaction_type,
    transaction_category,
    amount,
    currency,
    amount_usd,
    channel,
    branch_id,
    merchant_name,
    merchant_category,
    transaction_country,
    transaction_city,
    transaction_status,
    response_code,
    is_fraud,
    fraud_score,
    latitude,
    longitude
from {{ ref('stg_transactions') }}
