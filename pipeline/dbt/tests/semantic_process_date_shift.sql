{{ config(severity='warn') }}
-- D1.3 finding: process_date follows UTC-6 in all three countries, so it must
-- equal (transaction_date - 6h)::date. transaction_date is UTC (timestamptz).
select transaction_id, transaction_date, process_date
from {{ ref('srv_transactions') }}
where process_date <> cast((transaction_date at time zone 'UTC') - interval 6 hour as date)
