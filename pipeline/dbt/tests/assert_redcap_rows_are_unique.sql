-- Each REDCap row appears once: the pipeline's key must hold through staging.
-- Returns the duplicated keys; the test passes when it returns nothing.
select
    project,
    record_id,
    event,
    repeat_instrument,
    repeat_instance,
    count(*) as copies
from {{ ref('stg_redcap__records') }}
group by 1, 2, 3, 4, 5
having count(*) > 1
