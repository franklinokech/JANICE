-- KMC counts must add up: given <= recorded <= eligible, and eligible +
-- implausible + not recorded <= discharged alive. Returns rows that break this.
select *
from {{ ref('qi_neonatal_kmc_under_2000g') }}
where kmc_given > kmc_recorded
    or kmc_recorded > eligible
    or eligible + implausible_weight + weight_not_recorded > discharged_alive
