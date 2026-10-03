-- Final column set for bank.marketing_campaigns, in the migration's column
-- order (0001, T11). `start_date`/`end_date` are shifted (D11).
select
    campaign_id,
    campaign_name,
    description,
    campaign_type,
    campaign_objective,
    promoted_product,
    target_segment,
    target_country,
    {{ shift_date('start_date') }} as start_date,
    {{ shift_date('end_date') }} as end_date,
    budget,
    campaign_status,
    expected_conversion_rate
from {{ ref('stg_marketing_campaigns') }}
