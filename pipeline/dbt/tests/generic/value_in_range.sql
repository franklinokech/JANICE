{#
    Fails (or warns) for values outside a plausible range. NULLs pass: missing
    values are measured by completeness, not by this test.
    Use with severity: warn for clinical plausibility, so an odd value is seen
    by the data managers without stopping the whole build.
#}
{% test value_in_range(model, column_name, min_value, max_value) %}
select {{ column_name }}
from {{ model }}
where {{ column_name }} < {{ min_value }} or {{ column_name }} > {{ max_value }}
{% endtest %}
