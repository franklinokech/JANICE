{#
    Read REDCap values out of the JSONB `data` column safely.

    REDCap stores everything as text, and CIN forms use sentinels for
    "not recorded": -1 for numbers and codes, 1914-01-01 for dates. These
    macros turn sentinels, blanks and anything unparseable into NULL, so a
    missing temperature can never be counted as -1 °C.
    pg_input_is_valid (Postgres 16+) checks a value before casting, so one
    malformed entry cannot fail the whole build.
#}

{% macro redcap_text(field) -%}
    nullif(data ->> '{{ field }}', '')
{%- endmacro %}

{% macro redcap_number(field) -%}
    case
        when pg_input_is_valid(data ->> '{{ field }}', 'numeric')
            and (data ->> '{{ field }}')::numeric <> -1
            then (data ->> '{{ field }}')::numeric
    end
{%- endmacro %}

{% macro redcap_date(field) -%}
    case
        when pg_input_is_valid(data ->> '{{ field }}', 'date')
            and (data ->> '{{ field }}')::date <> date '1914-01-01'
            then (data ->> '{{ field }}')::date
    end
{%- endmacro %}

{#
    A yes/no question as a boolean. Codes differ between fields (yesno fields
    use 1/0, many radios use 1/2), so the "no" code is a parameter. Anything
    else, including -1 (empty), is NULL.
#}
{% macro redcap_yes(field, yes='1', no='0') -%}
    case data ->> '{{ field }}'
        when '{{ yes }}' then true
        when '{{ no }}' then false
    end
{%- endmacro %}

{#
    A weight in grams from a value field and its units field (1 = grams,
    2 = kilograms), rounded to whole grams. The units question is optional on
    the CIN form, so when it is missing the unit is inferred: under 10 must be
    kilograms, 200 and over must be grams; anything between is too ambiguous
    and stays NULL.
#}
{% macro redcap_weight_g(value_field, units_field) -%}
    round(case
        when {{ redcap_number(value_field) }} is null or {{ redcap_number(value_field) }} <= 0
            then null
        when data ->> '{{ units_field }}' = '2' then {{ redcap_number(value_field) }} * 1000
        when data ->> '{{ units_field }}' = '1' then {{ redcap_number(value_field) }}
        when {{ redcap_number(value_field) }} < 10 then {{ redcap_number(value_field) }} * 1000
        when {{ redcap_number(value_field) }} >= 200 then {{ redcap_number(value_field) }}
    end)::integer
{%- endmacro %}
