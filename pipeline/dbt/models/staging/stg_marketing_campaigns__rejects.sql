-- Typed, deduped staging for bank.marketing_campaigns (D8). No date shift here
-- (D11); `nullif(trim(x), '')` runs before every cast so a blank
-- source string becomes SQL NULL instead of an empty string or a
-- cast error. TIMESTAMP columns stay naive (no `timestamptz`): the
-- UTC interpretation and the shift both happen in serving (T11).
-- This sibling keeps the duplicate rows `stg_marketing_campaigns` drops.
with source as (
    select * from {{ source('raw', 'marketing_campaigns') }}
),

typed as (
    select
        cast(nullif(trim(campaign_id), '') as text) as campaign_id,
        cast(nullif(trim(campaign_name), '') as text) as campaign_name,
        cast(nullif(trim(description), '') as text) as description,
        cast(nullif(trim(campaign_type), '') as text) as campaign_type,
        cast(nullif(trim(campaign_objective), '') as text) as campaign_objective,
        cast(nullif(trim(promoted_product), '') as text) as promoted_product,
        cast(nullif(trim(target_segment), '') as text) as target_segment,
        cast(nullif(trim(target_country), '') as text) as target_country,
        cast(nullif(trim(start_date), '') as date) as start_date,
        cast(nullif(trim(end_date), '') as date) as end_date,
        cast(nullif(trim(budget), '') as numeric) as budget,
        cast(nullif(trim(campaign_status), '') as text) as campaign_status,
        cast(nullif(trim(expected_conversion_rate), '') as double precision) as expected_conversion_rate,
        {{ dedup_row_number('campaign_id') }} as dedup_row_number
    from source
)

select * exclude (dedup_row_number)
from typed
where dedup_row_number > 1
