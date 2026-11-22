-- Pilot indicator 3: kangaroo mother care (KMC) for babies under 2000 g.
--
-- Grain: one row per site and admission month.
--   numerator   kmc_given: KMC recorded as given
--   denominator eligible: birth weight 300 to 1999 g, discharged alive
-- Babies who died or were referred, absconded or left against advice are not
-- eligible: their stay may have ended before KMC could start.
-- KMC not documented counts as not given (the usual audit rule: "not
-- documented, not done"); documentation_completeness = kmc_recorded /
-- eligible shows how much of the rate rests on missing answers.
-- Weights under 300 or over 6000 g are implausible (the staging model warns
-- about them) and are counted apart, like a missing weight, rather than
-- deciding eligibility.

{% set plausible_min_g = 300 %}
{% set plausible_max_g = 6000 %}

with discharged_alive as (

    select
        site_id,
        admission_month,
        birth_weight_g,
        kmc_given,
        birth_weight_g between {{ plausible_min_g }} and {{ plausible_max_g }} as weight_plausible
    from {{ ref('stg_neonatal__admissions') }}
    where outcome = 'alive'
        -- Admissions without a usable date cannot be placed in a month
        and admission_month is not null

)

select
    site_id,
    admission_month,
    count(*) as discharged_alive,
    count(*) filter (where birth_weight_g is null) as weight_not_recorded,
    count(*) filter (where not weight_plausible) as implausible_weight,
    count(*) filter (where weight_plausible and birth_weight_g < 2000) as eligible,
    count(*) filter (
        where weight_plausible and birth_weight_g < 2000 and kmc_given is not null
    ) as kmc_recorded,
    count(*) filter (where weight_plausible and birth_weight_g < 2000 and kmc_given) as kmc_given,
    round(
        (count(*) filter (where weight_plausible and birth_weight_g < 2000 and kmc_given))::numeric
        / nullif(count(*) filter (where weight_plausible and birth_weight_g < 2000), 0),
        4
    ) as kmc_rate,
    round(
        (count(*) filter (
            where weight_plausible and birth_weight_g < 2000 and kmc_given is not null
        ))::numeric
        / nullif(count(*) filter (where weight_plausible and birth_weight_g < 2000), 0),
        4
    ) as documentation_completeness
from discharged_alive
group by 1, 2
