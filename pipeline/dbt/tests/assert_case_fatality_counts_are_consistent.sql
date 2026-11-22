-- In every indicator row, deaths <= known outcomes <= admissions, and known +
-- unknown outcomes = admissions. Returns rows that break this.
select *
from {{ ref('qi_neonatal_case_fatality_by_birth_weight') }}
where deaths > known_outcome
    or known_outcome > admissions
    or known_outcome + unknown_outcome <> admissions
