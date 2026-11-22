-- Hypothermia counts must add up: mild + moderate + severe = hypothermic,
-- hypothermic <= assessed, assessed + implausible = recorded, recorded <=
-- admissions. Returns rows that break this.
select *
from {{ ref('qi_neonatal_hypothermia_on_admission') }}
where mild + moderate + severe <> hypothermic
    or hypothermic > assessed
    or assessed + implausible_temp <> temp_recorded
    or temp_recorded > admissions
