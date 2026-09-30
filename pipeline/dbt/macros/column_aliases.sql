-- Select expression for a canonical column of a source table, folding in the
-- aliases declared in `var('column_aliases')[table]` ({alias: canonical}).
-- With no aliases it is just the column name, so default behaviour is
-- unchanged. With aliases, `COLUMNS('^(a|b)$')` matches whichever of the
-- names exist in the unioned source, so it works both when the alias is in
-- only some files (NULL elsewhere via union_by_name) and when it exists in
-- no file at all (only the canonical column matches).
{% macro column_alias_expr(table, column) %}
    {%- set aliases = var('column_aliases', {}).get(table, {}) -%}
    {%- set names = [column] -%}
    {%- for alias, canonical in aliases.items() -%}
        {%- if canonical == column -%}{%- do names.append(alias) -%}{%- endif -%}
    {%- endfor -%}
    {%- if names | length == 1 -%}
        {{ column }}
    {%- else -%}
        coalesce(*COLUMNS('^({{ names | join("|") }})$'))
    {%- endif -%}
{% endmacro %}
