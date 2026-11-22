{{ config(severity='warn') }}
-- Fields on the CIN neonatal form whose branching logic can never be true
-- (e.g. [is_minimum] = '0' and [is_minimum] = '1'), so REDCap never shows them.
-- No indicator may use them: they would always read as "not done".
-- If one starts receiving data, the form has changed and these indicators
-- should be reviewed. Returns each such field with how many records hold it.
-- (Checkbox fields are left out: REDCap exports 0 for every unticked box.)
{% set retired = [
    'random', 'twin_delivery', 'gravity', 'premature_rapture_of_membr',
    'time_of_admission_document', 'time_baby_seen', 'severe_vomiting',
    'partial_focal_fits', 'high_pitched_cry', 'diarrhoea', 'stirdor', 'eye_pus',
    'redced_movement_floppy', 'skin', 'gest_size', 'neo_std_monit_chart_pre',
    'mechanical_ventilation', 'time_to_start_feeds_after',
    'opv', 'bcg', 'other_disch_diag_old'
] %}
{% for field in retired %}
select '{{ field }}' as field, count(*) as records_with_data
from {{ ref('stg_redcap__records') }}
where project = 'neonatal' and coalesce(data ->> '{{ field }}', '') not in ('', '-1')
having count(*) > 0
{% if not loop.last %}union all{% endif %}
{% endfor %}
