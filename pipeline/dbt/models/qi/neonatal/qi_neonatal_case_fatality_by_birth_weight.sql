-- Pilot indicator 1: neonatal case fatality by birth-weight band.
--
-- Grain: one row per site, admission month and birth-weight band.
--   numerator   deaths
--   denominator admissions whose outcome is known (alive or dead at discharge)
-- Referred, absconded and discharged-against-advice babies are left out of
-- the denominator, because their fate is unknown; they are counted in
-- unknown_outcome so readers can judge how certain each rate is.
-- Babies with no usable birth weight form the band "not_recorded", which
-- gives the indicator's documentation completeness.
-- Band labels end in "g" because YAML (used by the tests) reads a bare
-- 1000_1499 as the number 10001499.
-- Small numbers are suppressed by the query service, not here.

with admissions as (

    select
        site_id,
        admission_month,
        outcome_known,
        died,
        case
            when birth_weight_g is null then 'not_recorded'
            when birth_weight_g < 1000 then 'under_1000g'
            when birth_weight_g < 1500 then '1000_1499g'
            when birth_weight_g < 2500 then '1500_2499g'
            else '2500g_plus'
        end as birth_weight_band
    from {{ ref('stg_neonatal__admissions') }}
    -- An admission without a usable date cannot be placed in a month; the
    -- staging model's admission_date test reports how many there are
    where admission_month is not null

)

select
    site_id,
    admission_month,
    birth_weight_band,
    case birth_weight_band
        when 'under_1000g' then 1
        when '1000_1499g' then 2
        when '1500_2499g' then 3
        when '2500g_plus' then 4
        else 5
    end as band_order,
    count(*) as admissions,
    count(*) filter (where outcome_known) as known_outcome,
    count(*) filter (where died) as deaths,
    count(*) filter (where not outcome_known) as unknown_outcome,
    round(
        (count(*) filter (where died))::numeric
        / nullif(count(*) filter (where outcome_known), 0),
        4
    ) as case_fatality_rate
from admissions
group by 1, 2, 3
