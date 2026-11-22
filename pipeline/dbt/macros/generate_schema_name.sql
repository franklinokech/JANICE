{#
    Build models in the schema they name (stg, later marts and qi), not dbt's
    default "<target schema>_stg". The schema_prefix var is empty in real
    environments; tests set it so each test run builds in its own schemas.
#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {{ var('schema_prefix', '') ~ (custom_schema_name or target.schema) | trim }}
{%- endmacro %}
