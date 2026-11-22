# 10. List REDCap projects in a reviewed config file

- **Status:** Accepted
- **Date:** 2026-11-22
- **Deciders:** Franklin Okech

## Context

JANICE started with three fixed CIN projects (neonatal, paediatrics, maternity), each with a `hosp_id` site field. More projects are expected, and their number is not known in advance. They may live on other REDCap servers, use a different site field, or need other fields kept in clear text. The record ID does not vary in a way that matters: REDCap always makes it the first field.

The design doc planned a "REDCap project" model in the Django admin, so data managers could add projects themselves. That needs the Django models, an API or database link between Django and Dagster, and dynamic partitions synced by a sensor. None of these exist yet, and projects will change rarely during the pilot.

## Decision

List projects in `pipeline/src/janice_pipeline/projects/projects.yaml`, committed to the repository and changed only by pull request.

- Each entry needs a `key` (lowercase letters, digits and `_`, at most 40 characters; it becomes the table name `raw_<key>`) and a `site_field`. These are optional:
  - `description`
  - `keep_in_clear`
  - `token_env` (default `REDCAP_TOKEN_<KEY>`)
  - `api_url` (default `REDCAP_API_URL`)
  - `server_timezone` (default `UTC`)
  - `dictionary_file`
  - `enabled`
- The file holds no secrets, only the name of each token's environment variable.
- It is validated when Dagster loads. Unknown settings, unsafe or duplicate keys, non-https URLs and unknown time zones are refused.
- Dagster builds one `redcap_staging` partition per enabled project, each with its own DuckDB staging file.
- Code reads projects only through `load_projects()`, so the source of the list can change without touching staging.
- `JANICE_PROJECTS_FILE` can point to another file, for example a staging-server list.

## Consequences

- Adding, changing or pausing a project is a reviewed, versioned change that can be rolled back, with no code change.
- Mistakes fail when Dagster starts rather than mid-run. A misspelt setting is refused instead of silently ignored, so a field can't be hashed or exposed by accident.
- Adding a project needs a merge and a redeploy, so data managers can't do it alone. That is acceptable for the pilot.
- Warehouse keys must include the project, because record IDs repeat across projects.
- dbt needs a small `stg_<project>` model per project to map its fields to the common shape the indicators use.

## Alternatives considered

- **Django admin model, read by Dagster through a sensor and dynamic partitions.** Lets data managers self-serve, but needs the Django side first. This remains the planned next step when self-service is needed; only `load_projects()` would change.
- **Hard-coded list of units in code.** Simple, but every new project would be a code change. This was the original approach, replaced by this decision.
- **Environment variables only.** No review trail, and settings like `keep_in_clear` lists don't fit well in environment variables.
