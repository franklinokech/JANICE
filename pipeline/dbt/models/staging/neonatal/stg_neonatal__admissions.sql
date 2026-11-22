-- One row per neonatal admission: the CIN neonatal form's fields that the
-- indicators use, cleaned once.
--
-- * Sentinels become NULL: -1 for numbers and codes, 1914-01-01 for dates.
-- * Weights are in grams, whatever unit was recorded (see redcap_weight_g).
-- * Yes/no questions are booleans; their "no" code differs by field.
-- * is_full_form: minimum records hide many fields (branching on
--   [is_minimum] = '0'), so indicators using those fields must count only
--   full-form records in their denominators.
--
-- Field names and codes: CIN Standard Neonatal Tool data dictionary.

with records as (

    select * from {{ ref('stg_redcap__records') }}
    where project = 'neonatal'
        and not is_repeat_instance

)

select
    record_key,
    record_id,
    site_id,

    -- Dates
    {{ redcap_date('date_adm') }} as admission_date,
    date_trunc('month', {{ redcap_date('date_adm') }})::date as admission_month,
    {{ redcap_date('date_discharge') }} as discharge_date,

    -- Record type
    case data ->> 'is_minimum' when '1' then false when '0' then true end as is_full_form,

    -- Baby
    {{ redcap_weight_g('birth_wt', 'birth_wt_units') }} as birth_weight_g,
    {{ redcap_number('gest') }} as gestation_weeks,

    -- Admission examination
    {{ redcap_number('temperature_degrees_celciu') }} as admission_temp_c,
    {{ redcap_yes('oxygen_saturation_measured') }} as spo2_measured,
    {{ redcap_number('oxygen_saturation') }} as spo2_percent,
    {{ redcap_yes('oxygen_ordered') }} as oxygen_prescribed,

    -- Care
    {{ redcap_yes('k_mother_care') }} as kmc_given,
    {{ redcap_yes('mother_anten_corti', no='2') }} as antenatal_steroids,
    {{ redcap_yes('cpap') }} as cpap_given,
    {{ redcap_number('lowest_temperature') }} as lowest_temp_c,

    -- Outcome (codes from the "Outcome at discharge" dropdown)
    case data ->> 'outcome'
        when '1' then 'alive'
        when '2' then 'dead'
        when '3' then 'referred'
        when '4' then 'absconded'
        when '5' then 'discharged_against_advice'
    end as outcome,
    -- Case fatality counts only babies whose fate is known
    data ->> 'outcome' in ('1', '2') as outcome_known,
    data ->> 'outcome' = '2' as died,

    loaded_at
from records
