-- Typed, deduped staging for bank.branches (D8). No date shift here
-- (D11); `nullif(trim(x), '')` runs before every cast so a blank
-- source string becomes SQL NULL instead of an empty string or a
-- cast error. TIMESTAMP columns stay naive (no `timestamptz`): the
-- UTC interpretation and the shift both happen in serving (T11).
with source as (
    select * from {{ source('raw', 'branches') }}
),

typed as (
    select
        cast(nullif(trim(branch_id), '') as text) as branch_id,
        cast(nullif(trim(branch_code), '') as text) as branch_code,
        cast(nullif(trim(branch_name), '') as text) as branch_name,
        cast(nullif(trim(branch_type), '') as text) as branch_type,
        cast(nullif(trim(address), '') as text) as address,
        cast(nullif(trim(city), '') as text) as city,
        cast(nullif(trim(state), '') as text) as state,
        cast(nullif(trim(country), '') as text) as country,
        cast(nullif(trim(postal_code), '') as text) as postal_code,
        cast(nullif(trim(geographic_zone), '') as text) as geographic_zone,
        cast(nullif(trim(phone), '') as text) as phone,
        cast(nullif(trim(email), '') as text) as email,
        cast(nullif(trim(opening_time), '') as time) as opening_time,
        cast(nullif(trim(closing_time), '') as time) as closing_time,
        cast(nullif(trim(has_atms), '') as boolean) as has_atms,
        cast(nullif(trim(atm_count), '') as integer) as atm_count,
        cast(nullif(trim(has_teller_windows), '') as boolean) as has_teller_windows,
        cast(nullif(trim(teller_window_count), '') as integer) as teller_window_count,
        cast(nullif(trim(latitude), '') as double precision) as latitude,
        cast(nullif(trim(longitude), '') as double precision) as longitude,
        cast(nullif(trim(branch_opening_date), '') as date) as branch_opening_date,
        cast(nullif(trim(branch_status), '') as text) as branch_status,
        {{ dedup_row_number('branch_id') }} as dedup_row_number
    from source
)

select * exclude (dedup_row_number)
from typed
where dedup_row_number = 1
