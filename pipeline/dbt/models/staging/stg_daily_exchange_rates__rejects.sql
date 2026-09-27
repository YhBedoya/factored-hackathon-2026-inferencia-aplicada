-- Typed, deduped staging for bank.daily_exchange_rates (D8). No date shift here
-- (D11); `nullif(trim(x), '')` runs before every cast so a blank
-- source string becomes SQL NULL instead of an empty string or a
-- cast error. TIMESTAMP columns stay naive (no `timestamptz`): the
-- UTC interpretation and the shift both happen in serving (T11).
-- This sibling keeps the duplicate rows `stg_daily_exchange_rates` drops.
with source as (
    select * from {{ source('raw', 'daily_exchange_rates') }}
),

typed as (
    select
        cast(nullif(trim(date), '') as date) as date,
        cast(nullif(trim(source_currency), '') as text) as source_currency,
        cast(nullif(trim(target_currency), '') as text) as target_currency,
        cast(nullif(trim(exchange_rate), '') as numeric) as exchange_rate,
        cast(nullif(trim(buy_rate), '') as numeric) as buy_rate,
        cast(nullif(trim(sell_rate), '') as numeric) as sell_rate,
        cast(nullif(trim(source), '') as text) as source,
        {{ dedup_row_number('date, source_currency, target_currency') }} as dedup_row_number
    from source
)

select * exclude (dedup_row_number)
from typed
where dedup_row_number > 1
