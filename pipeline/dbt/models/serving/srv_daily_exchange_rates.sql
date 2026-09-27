-- Final column set for bank.daily_exchange_rates, in the migration's column
-- order (0001, T11). `date` is shifted (D11); the natural key is the
-- composite (date, source_currency, target_currency), checked by the
-- `unique_combination` generic test in schema.yml.
select
    {{ shift_date('date') }} as date,
    source_currency,
    target_currency,
    exchange_rate,
    buy_rate,
    sell_rate,
    source
from {{ ref('stg_daily_exchange_rates') }}
