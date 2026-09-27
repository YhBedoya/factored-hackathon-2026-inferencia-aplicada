-- Typed, deduped staging for bank.customers (D8). No date shift here
-- (D11); `nullif(trim(x), '')` runs before every cast so a blank
-- source string becomes SQL NULL instead of an empty string or a
-- cast error. TIMESTAMP columns stay naive (no `timestamptz`): the
-- UTC interpretation and the shift both happen in serving (T11).
-- This sibling keeps the duplicate rows `stg_customers` drops.
with source as (
    select * from {{ source('raw', 'customers') }}
),

typed as (
    select
        cast(nullif(trim(customer_id), '') as text) as customer_id,
        cast(nullif(trim(document_number), '') as text) as document_number,
        cast(nullif(trim(document_type), '') as text) as document_type,
        cast(nullif(trim(first_name), '') as text) as first_name,
        cast(nullif(trim(last_name), '') as text) as last_name,
        cast(nullif(trim(date_of_birth), '') as date) as date_of_birth,
        cast(nullif(trim(gender), '') as text) as gender,
        cast(nullif(trim(email), '') as text) as email,
        cast(nullif(trim(mobile_phone), '') as text) as mobile_phone,
        cast(nullif(trim(landline_phone), '') as text) as landline_phone,
        cast(nullif(trim(address), '') as text) as address,
        cast(nullif(trim(city), '') as text) as city,
        cast(nullif(trim(state), '') as text) as state,
        cast(nullif(trim(country), '') as text) as country,
        cast(nullif(trim(postal_code), '') as text) as postal_code,
        cast(nullif(trim(detected_accent), '') as text) as detected_accent,
        cast(nullif(trim(segment), '') as text) as segment,
        cast(nullif(trim(credit_score), '') as double precision) as credit_score,
        cast(nullif(trim(estimated_monthly_income), '') as numeric) as estimated_monthly_income,
        cast(nullif(trim(occupation), '') as text) as occupation,
        cast(nullif(trim(marital_status), '') as text) as marital_status,
        cast(nullif(trim(education_level), '') as text) as education_level,
        cast(nullif(trim(registration_date), '') as timestamp) as registration_date,
        cast(nullif(trim(registration_branch_id), '') as text) as registration_branch_id,
        cast(nullif(trim(customer_status), '') as text) as customer_status,
        cast(nullif(trim(last_updated), '') as timestamp) as last_updated,
        cast(nullif(trim(accepts_marketing), '') as boolean) as accepts_marketing,
        {{ dedup_row_number('customer_id') }} as dedup_row_number
    from source
)

select * exclude (dedup_row_number)
from typed
where dedup_row_number > 1
