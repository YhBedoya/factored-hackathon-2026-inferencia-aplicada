{#
    Whole-week date shift (D11): serving moves every DATE/TIMESTAMP column
    forward by `var('date_offset_days')` days, so weekday patterns and
    relative expressions ("el martes pasado") stay consistent with the
    simulated "now", while intervals between two shifted columns (ages,
    durations) are unchanged. TIME-of-day columns are never shifted (they
    aren't dates) and don't go through either macro.

    `var('date_offset_days')` is called with no default, so a missing var
    fails the build instead of silently shifting by zero (T11 acceptance).

    DuckDB: `date + interval (n) day` and `timestamp + interval (n) day`
    both come back as a plain (naive) TIMESTAMP, never a DATE, so
    `shift_date` casts back to `date` explicitly. `shift_timestamp` casts
    the shifted naive value to `timestamptz`, which the DuckDB session
    (`profiles.yml`'s `TimeZone: "UTC"`) interprets as UTC (D1), matching
    the naive-UTC convention staging already casts every TIMESTAMP into.
#}
{% macro shift_date(column) -%}
    cast({{ column }} + interval ({{ var('date_offset_days') }}) day as date)
{%- endmacro %}

{% macro shift_timestamp(column) -%}
    cast({{ column }} + interval ({{ var('date_offset_days') }}) day as timestamptz)
{%- endmacro %}
