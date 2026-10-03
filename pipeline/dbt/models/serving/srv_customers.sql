-- Final column set for bank.customers, in the migration's column order
-- (0001, T11). `date_of_birth` and the two TIMESTAMPs are shifted (D11);
-- ages stay correct since both `date_of_birth` and "now" move together.
select
    customer_id,
    document_number,
    document_type,
    first_name,
    last_name,
    {{ shift_date('date_of_birth') }} as date_of_birth,
    gender,
    email,
    mobile_phone,
    landline_phone,
    address,
    city,
    state,
    country,
    postal_code,
    detected_accent,
    segment,
    credit_score,
    estimated_monthly_income,
    occupation,
    marital_status,
    education_level,
    {{ shift_timestamp('registration_date') }} as registration_date,
    registration_branch_id,
    customer_status,
    {{ shift_timestamp('last_updated') }} as last_updated,
    accepts_marketing
from {{ ref('stg_customers') }}
