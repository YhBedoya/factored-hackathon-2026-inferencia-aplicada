-- Typed, deduped staging for bank.digital_events (D8). No date shift here
-- (D11); `nullif(trim(x), '')` runs before every cast so a blank
-- source string becomes SQL NULL instead of an empty string or a
-- cast error. TIMESTAMP columns stay naive (no `timestamptz`): the
-- UTC interpretation and the shift both happen in serving (T11).
with source as (
    select * from {{ source('raw', 'digital_events') }}
),

typed as (
    select
        cast(nullif(trim(event_id), '') as text) as event_id,
        cast(nullif(trim(event_date), '') as timestamp) as event_date,
        cast(nullif(trim(process_date), '') as date) as process_date,
        cast(nullif(trim(customer_id), '') as text) as customer_id,
        cast(nullif(trim(session_id), '') as text) as session_id,
        cast(nullif(trim(event_type), '') as text) as event_type,
        cast(nullif(trim(event_category), '') as text) as event_category,
        cast(nullif(trim(channel), '') as text) as channel,
        cast(nullif(trim(platform), '') as text) as platform,
        cast(nullif(trim(browser), '') as text) as browser,
        cast(nullif(trim(app_version), '') as text) as app_version,
        cast(nullif(trim(page_url), '') as text) as page_url,
        cast(nullif(trim(page_title), '') as text) as page_title,
        cast(nullif(trim(action), '') as text) as action,
        cast(nullif(trim(element_id), '') as text) as element_id,
        cast(nullif(trim(product_id), '') as text) as product_id,
        cast(nullif(trim(event_value), '') as double precision) as event_value,
        cast(nullif(trim(duration_seconds), '') as double precision) as duration_seconds,
        cast(nullif(trim(ip_address), '') as text) as ip_address,
        cast(nullif(trim(ip_country), '') as text) as ip_country,
        cast(nullif(trim(ip_city), '') as text) as ip_city,
        cast(nullif(trim(is_mobile), '') as boolean) as is_mobile,
        cast(nullif(trim(referrer), '') as text) as referrer,
        cast(nullif(trim(utm_source), '') as text) as utm_source,
        cast(nullif(trim(utm_medium), '') as text) as utm_medium,
        cast(nullif(trim(utm_campaign), '') as text) as utm_campaign,
        {{ dedup_row_number('event_id') }} as dedup_row_number
    from source
)

select * exclude (dedup_row_number)
from typed
where dedup_row_number = 1
