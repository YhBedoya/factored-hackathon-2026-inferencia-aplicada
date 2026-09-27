-- Typed, deduped staging for bank.products (D8). No date shift here
-- (D11); `nullif(trim(x), '')` runs before every cast so a blank
-- source string becomes SQL NULL instead of an empty string or a
-- cast error. TIMESTAMP columns stay naive (no `timestamptz`): the
-- UTC interpretation and the shift both happen in serving (T11).
-- This sibling keeps the duplicate rows `stg_products` drops.
with source as (
    select * from {{ source('raw', 'products') }}
),

typed as (
    select
        cast(nullif(trim(product_id), '') as text) as product_id,
        cast(nullif(trim(customer_id), '') as text) as customer_id,
        cast(nullif(trim(product_type), '') as text) as product_type,
        cast(nullif(trim(product_number), '') as text) as product_number,
        cast(nullif(trim(currency), '') as text) as currency,
        cast(nullif(trim(current_balance), '') as numeric) as current_balance,
        cast(nullif(trim(credit_limit), '') as numeric) as credit_limit,
        cast(nullif(trim(interest_rate), '') as numeric) as interest_rate,
        cast(nullif(trim(opening_date), '') as date) as opening_date,
        cast(nullif(trim(expiration_date), '') as date) as expiration_date,
        cast(nullif(trim(opening_branch_id), '') as text) as opening_branch_id,
        cast(nullif(trim(product_status), '') as text) as product_status,
        cast(nullif(trim(opening_channel), '') as text) as opening_channel,
        cast(nullif(trim(has_linked_app), '') as boolean) as has_linked_app,
        cast(nullif(trim(days_past_due), '') as integer) as days_past_due,
        cast(nullif(trim(last_transaction_date), '') as timestamp) as last_transaction_date,
        cast(nullif(trim(last_updated), '') as timestamp) as last_updated,
        {{ dedup_row_number('product_id') }} as dedup_row_number
    from source
)

select * exclude (dedup_row_number)
from typed
where dedup_row_number > 1
