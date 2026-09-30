{{ config(severity='warn') }}
-- EDA semantic check (03 §3): last_updated after the load date. Reference is
-- current_date, which stays valid after the date shift (the shift moves data
-- up to today, never past it).
select 'srv_customers' as table_name, customer_id as pk
from {{ ref('srv_customers') }}
where cast(last_updated as date) > current_date
union all
select 'srv_products', product_id
from {{ ref('srv_products') }}
where cast(last_updated as date) > current_date
