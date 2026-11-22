-- A record's rows must agree on its site, or site_id (taken across the
-- record's rows) would silently pick one. Returns records with two sites.
select
    records.project,
    records.record_id,
    count(distinct records.data ->> projects.site_field) as sites
from {{ source('raw', 'redcap_records') }} as records
inner join {{ source('raw', 'projects') }} as projects
    on projects.project = records.project
where nullif(records.data ->> projects.site_field, '') is not null
group by 1, 2
having count(distinct records.data ->> projects.site_field) > 1
