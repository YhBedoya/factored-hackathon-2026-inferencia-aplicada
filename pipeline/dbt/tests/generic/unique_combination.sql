{#
    Project generic test for a composite natural key (D8): fails a build if
    any combination of `combination_of_columns` repeats in the model. Used
    at model level (no `column_name`) for `srv_daily_exchange_rates`, whose
    PK is the triple (date, source_currency, target_currency) rather than a
    single column, so the ordinary `unique`/`not_null` column tests don't
    apply.
#}
{% test unique_combination(model, combination_of_columns) %}

with duplicates as (
    select
        {{ combination_of_columns | join(', ') }},
        count(*) as row_count
    from {{ model }}
    group by {{ combination_of_columns | join(', ') }}
    having count(*) > 1
)

select * from duplicates

{% endtest %}
