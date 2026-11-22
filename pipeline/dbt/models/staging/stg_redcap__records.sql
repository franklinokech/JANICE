-- One row per REDCap row (a record, or one repeat instance of an instrument),
-- for every project, with the project's site read from the field the project
-- registry names (raw.projects.site_field).
--
-- Fields stay in the JSONB column `data`; the per-project models built on this
-- view pick out and cast the fields each indicator needs.

with records as (

    select * from {{ source('raw', 'redcap_records') }}

),

projects as (

    select * from {{ source('raw', 'projects') }}

),

with_row_site as (

    select
        records.project,
        records.record_id,
        records.event,
        records.repeat_instrument,
        records.repeat_instance,
        nullif(records.data ->> projects.site_field, '') as row_site_id,
        records.data,
        records.loaded_at
    from records
    inner join projects on projects.project = records.project

)

select
    project,
    record_id,
    -- Record IDs repeat across projects, so the project is part of the key
    project || ':' || record_id as record_key,
    event,
    repeat_instrument,
    repeat_instance,
    repeat_instrument <> '' as is_repeat_instance,
    -- Repeat instances do not carry the site field; they belong to their
    -- record's site (a separate test checks a record never has two sites)
    max(row_site_id) over (partition by project, record_id) as site_id,
    data,
    loaded_at
from with_row_site
