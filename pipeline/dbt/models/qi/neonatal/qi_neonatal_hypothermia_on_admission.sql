-- Pilot indicator 2: hypothermia on admission.
--
-- Grain: one row per site and admission month.
--   numerator   hypothermic: admission temperature below 36.5 °C
--   denominator assessed: a plausible admission temperature was recorded
-- Graded with the WHO bands: mild 36.0 to 36.4, moderate 32.0 to 35.9,
-- severe below 32.0 °C.
--
-- A temperature outside 25 to 43 °C is almost certainly a typing error
-- (4.2 for 34.2), and counting it would report severe hypothermia that never
-- happened. Such values are left out of the rate and counted in
-- implausible_temp; the staging model's warning test lists them for the data
-- managers. Documentation completeness = temp_recorded / admissions.

{% set plausible_min = 25 %}
{% set plausible_max = 43 %}

with admissions as (

    select
        site_id,
        admission_month,
        admission_temp_c as temp_c,
        admission_temp_c between {{ plausible_min }} and {{ plausible_max }} as is_plausible
    from {{ ref('stg_neonatal__admissions') }}
    -- Admissions without a usable date cannot be placed in a month
    where admission_month is not null

)

select
    site_id,
    admission_month,
    count(*) as admissions,
    count(temp_c) as temp_recorded,
    count(*) filter (where not is_plausible) as implausible_temp,
    count(*) filter (where is_plausible) as assessed,
    count(*) filter (where is_plausible and temp_c < 36.5) as hypothermic,
    count(*) filter (where is_plausible and temp_c >= 36.0 and temp_c < 36.5) as mild,
    count(*) filter (where is_plausible and temp_c >= 32.0 and temp_c < 36.0) as moderate,
    count(*) filter (where is_plausible and temp_c < 32.0) as severe,
    round(
        (count(*) filter (where is_plausible and temp_c < 36.5))::numeric
        / nullif(count(*) filter (where is_plausible), 0),
        4
    ) as hypothermia_rate,
    round(count(temp_c)::numeric / count(*), 4) as documentation_completeness
from admissions
group by 1, 2
