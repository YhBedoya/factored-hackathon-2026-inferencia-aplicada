-- Final column set for bank.branches, in the migration's column order
-- (0001, T11). `branch_opening_date` is shifted (D11); `opening_time` and
-- `closing_time` are TIME-of-day and are never shifted.
select
    branch_id,
    branch_code,
    branch_name,
    branch_type,
    address,
    city,
    state,
    country,
    postal_code,
    geographic_zone,
    phone,
    email,
    opening_time,
    closing_time,
    has_atms,
    atm_count,
    has_teller_windows,
    teller_window_count,
    latitude,
    longitude,
    {{ shift_date('branch_opening_date') }} as branch_opening_date,
    branch_status
from {{ ref('stg_branches') }}
