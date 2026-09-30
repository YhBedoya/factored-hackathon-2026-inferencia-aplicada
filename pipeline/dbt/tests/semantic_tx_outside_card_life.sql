{{ config(severity='warn') }}
-- EDA semantic check (03 §3): a transaction dated before its product's
-- opening_date or after its expiration_date. Both sides are shifted by the
-- same offset, so the comparison holds after the date shift.
select t.transaction_id, t.product_id
from {{ ref('srv_transactions') }} as t
join {{ ref('srv_products') }} as p on p.product_id = t.product_id
where cast(t.transaction_date as date) < p.opening_date
   or cast(t.transaction_date as date) > p.expiration_date
