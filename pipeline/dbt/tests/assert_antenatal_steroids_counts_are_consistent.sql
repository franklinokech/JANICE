-- Antenatal steroids counts must add up: given <= recorded <= eligible, and
-- eligible + implausible + not recorded <= admissions. Returns rows that break this.
select *
from {{ ref('qi_neonatal_antenatal_steroids_preterm') }}
where steroids_given > steroids_recorded
    or steroids_recorded > eligible
    or eligible + implausible_gestation + gestation_not_recorded > admissions
