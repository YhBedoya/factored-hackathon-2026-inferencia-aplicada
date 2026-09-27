-- Typed, deduped staging for bank.transactions (D8). No date shift here
-- (D11); `nullif(trim(x), '')` runs before every cast so a blank
-- source string becomes SQL NULL instead of an empty string or a
-- cast error. TIMESTAMP columns stay naive (no `timestamptz`): the
-- UTC interpretation and the shift both happen in serving (T11).
with source as (
    select * from {{ source('raw', 'transactions') }}
),

typed as (
    select
        cast(nullif(trim(transaction_id), '') as text) as transaction_id,
        cast(nullif(trim(transaction_date), '') as timestamp) as transaction_date,
        cast(nullif(trim(process_date), '') as date) as process_date,
        cast(nullif(trim(product_id), '') as text) as product_id,
        cast(nullif(trim(customer_id), '') as text) as customer_id,
        cast(nullif(trim(transaction_type), '') as text) as transaction_type,
        cast(nullif(trim(transaction_category), '') as text) as transaction_category,
        cast(nullif(trim(amount), '') as numeric) as amount,
        cast(nullif(trim(currency), '') as text) as currency,
        cast(nullif(trim(amount_usd), '') as numeric) as amount_usd,
        cast(nullif(trim(channel), '') as text) as channel,
        cast(nullif(trim(branch_id), '') as text) as branch_id,
        cast(nullif(trim(merchant_name), '') as text) as merchant_name,
        cast(nullif(trim(merchant_category), '') as text) as merchant_category,
        cast(nullif(trim(transaction_country), '') as text) as transaction_country,
        cast(nullif(trim(transaction_city), '') as text) as transaction_city,
        cast(nullif(trim(transaction_status), '') as text) as transaction_status,
        cast(nullif(trim(response_code), '') as text) as response_code,
        cast(nullif(trim(is_fraud), '') as boolean) as is_fraud,
        cast(nullif(trim(fraud_score), '') as numeric) as fraud_score,
        cast(nullif(trim(latitude), '') as double precision) as latitude,
        cast(nullif(trim(longitude), '') as double precision) as longitude,
        {{ dedup_row_number('transaction_id') }} as dedup_row_number
    from source
)

select * exclude (dedup_row_number)
from typed
where dedup_row_number = 1
