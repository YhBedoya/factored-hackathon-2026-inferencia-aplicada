{#
    Dedup on a primary key (D8): staging models rank each source row within
    its PK partition, keep rank 1 (`stg_<t>.sql`) and send the rest to
    `stg_<t>__rejects.sql`. No ORDER BY: which duplicate is "first" is
    arbitrary, but it's the same file scan every run for the same input
    Parquet, so a rebuild is deterministic (03 §2, "Determinism").
#}
{% macro dedup_row_number(partition_by) -%}
    row_number() over (partition by {{ partition_by }})
{%- endmacro %}
