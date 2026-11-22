-- Pilot indicator 5: oxygen saturation measured at admission.
--
-- Grain: one row per site and admission month.
--   numerator   spo2_measured: oxygen saturation recorded as measured
--   denominator eligible: full-form admissions
-- The question only appears on full-form records ([is_minimum] = '0'), so
-- minimum records are not eligible: counting them would read as "not
-- measured" when the question was never asked (indicator conventions,
-- rule 12). Records whose form type is unknown are counted apart.
-- A care indicator: not documented counts as not measured (rule 6);
-- documentation_completeness shows how much of the rate rests on unanswered
-- questions.

with admissions as (

    select
        site_id,
        admission_month,
        is_full_form,
        spo2_measured
    from {{ ref('stg_neonatal__admissions') }}
    -- Admissions without a usable date cannot be placed in a month
    where admission_month is not null

)

select
    site_id,
    admission_month,
    count(*) as admissions,
    count(*) filter (where is_full_form is false) as minimum_form,
    count(*) filter (where is_full_form is null) as form_type_not_recorded,
    count(*) filter (where is_full_form) as eligible,
    count(*) filter (where is_full_form and spo2_measured is not null) as spo2_recorded,
    count(*) filter (where is_full_form and spo2_measured) as spo2_measured,
    round(
        (count(*) filter (where is_full_form and spo2_measured))::numeric
        / nullif(count(*) filter (where is_full_form), 0),
        4
    ) as spo2_measured_rate,
    round(
        (count(*) filter (where is_full_form and spo2_measured is not null))::numeric
        / nullif(count(*) filter (where is_full_form), 0),
        4
    ) as documentation_completeness
from admissions
group by 1, 2
