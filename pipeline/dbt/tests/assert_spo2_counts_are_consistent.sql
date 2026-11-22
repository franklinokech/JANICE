-- Oxygen saturation counts must add up: measured <= recorded <= eligible, and
-- eligible + minimum + form type not recorded = admissions. Returns rows that break this.
select *
from {{ ref('qi_neonatal_spo2_measured_on_admission') }}
where spo2_measured > spo2_recorded
    or spo2_recorded > eligible
    or eligible + minimum_form + form_type_not_recorded <> admissions
