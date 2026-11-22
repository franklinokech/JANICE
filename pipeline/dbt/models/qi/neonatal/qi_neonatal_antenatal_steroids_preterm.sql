-- Pilot indicator 4: antenatal corticosteroids for preterm babies.
--
-- Grain: one row per site, admission month and place of birth.
--   numerator   steroids_given: the mother was given antenatal corticosteroids
--   denominator eligible: gestation of 24 to 33 weeks, the window in which WHO
--               (2022) recommends antenatal corticosteroids
-- Steroids are given before birth, so every eligible baby counts, whatever
-- the outcome. Place of birth matters: the admitting hospital cared for the
-- mother of an inborn baby, but not of a baby born elsewhere, so results are
-- broken down into inborn, born_outside and place_not_recorded.
-- A care indicator: not documented counts as not given (indicator
-- conventions, rule 6); documentation_completeness shows how much of the rate
-- rests on unanswered questions.

{% set plausible_min_weeks = 22 %}
{% set plausible_max_weeks = 46 %}
{% set eligible_min_weeks = 24 %}
{% set eligible_below_weeks = 34 %}

with admissions as (

    select
        site_id,
        admission_month,
        gestation_weeks,
        antenatal_steroids,
        case
            when born_outside then 'born_outside'
            when not born_outside then 'inborn'
            else 'place_not_recorded'
        end as place_of_birth,
        gestation_weeks between {{ plausible_min_weeks }} and {{ plausible_max_weeks }}
            as gestation_plausible,
        gestation_weeks >= {{ eligible_min_weeks }} and gestation_weeks < {{ eligible_below_weeks }}
            as eligible_gestation
    from {{ ref('stg_neonatal__admissions') }}
    -- Admissions without a usable date cannot be placed in a month
    where admission_month is not null

)

select
    site_id,
    admission_month,
    place_of_birth,
    count(*) as admissions,
    count(*) filter (where gestation_weeks is null) as gestation_not_recorded,
    count(*) filter (where not gestation_plausible) as implausible_gestation,
    count(*) filter (where eligible_gestation) as eligible,
    count(*) filter (
        where eligible_gestation and antenatal_steroids is not null
    ) as steroids_recorded,
    count(*) filter (
        where eligible_gestation and antenatal_steroids
    ) as steroids_given,
    round(
        (count(*) filter (
            where eligible_gestation and antenatal_steroids
        ))::numeric
        / nullif(count(*) filter (where eligible_gestation), 0),
        4
    ) as steroids_rate,
    round(
        (count(*) filter (
            where eligible_gestation and antenatal_steroids is not null
        ))::numeric
        / nullif(count(*) filter (where eligible_gestation), 0),
        4
    ) as documentation_completeness
from admissions
group by 1, 2, 3
